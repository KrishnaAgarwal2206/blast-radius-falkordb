"""Git history: commits, authors, file/function-level changes, ownership, SZZ-lite blame."""
import math
import re
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

BOT = re.compile(r"(\[bot\]|renovate|dependabot|github-actions|opentelemetrybot)", re.I)
FIX = re.compile(r"\b(fix|fixes|fixed|revert|regression|bug|crash|hang|leak)\b", re.I)
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
PR = re.compile(r"\(#(\d+)\)")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def read_log(root: Path, months: int, src_prefixes: list[str]):
    """One pass over history with -U0 hunks. Returns list of commit dicts."""
    out = git(root, "log", f"--since={months}.months", "--no-merges", "-U0", "-p", "--no-renames",
              "--format=\x01%H|%an|%ae|%at|%s", "--", *src_prefixes)
    commits, cur, cur_file = [], None, None
    for line in out.splitlines():
        if line.startswith("\x01"):
            sha, an, ae, at, subj = line[1:].split("|", 4)
            cur = dict(sha=sha, author=an, email=ae.lower(), ts=int(at), msg=subj, files={})
            commits.append(cur)
            cur_file = None
        elif line.startswith("+++ b/") and cur is not None:
            cur_file = line[6:]
            cur["files"].setdefault(cur_file, dict(hunks=[], adds=0, dels=0, old=[]))
        elif line.startswith(("--- ", "diff --git", "index ", "new file", "deleted file")):
            continue
        elif line.startswith("@@") and cur_file:
            m = HUNK.match(line)
            if m:
                oa, ob, na, nb = m.groups()
                ob = 1 if ob is None else int(ob)
                nb = 1 if nb is None else int(nb)
                f = cur["files"][cur_file]
                f["hunks"].append((int(na), int(na) + max(nb, 1) - 1))
                if ob:
                    f["old"].append((int(oa), int(oa) + ob - 1))
        elif cur_file and line.startswith("+"):
            cur["files"][cur_file]["adds"] += 1
        elif cur_file and line.startswith("-"):
            cur["files"][cur_file]["dels"] += 1
    return commits


def compute_ownership(commits, known_files, file_service, halflife_days=90):
    now = max((c["ts"] for c in commits), default=time.time())
    svc, fil = defaultdict(Counter), defaultdict(Counter)
    for c in commits:
        if BOT.search(c["author"]) or BOT.search(c["email"]):
            continue
        w = math.exp(-math.log(2) * (now - c["ts"]) / 86400 / halflife_days)
        for f, d in c["files"].items():
            if f in known_files:
                wt = w * (1 + math.log1p(d["adds"] + d["dels"]))
                svc[file_service[f]][c["email"]] += wt
                fil[f][c["email"]] += wt
    owns = []
    for s, cnt in svc.items():
        tot = sum(cnt.values())
        for e, v in cnt.most_common(5):
            if v / tot >= 0.05:
                owns.append(dict(email=e, kind="Service", key=s, score=round(v / tot, 3)))
    for f, cnt in fil.items():
        tot = sum(cnt.values())
        e, v = cnt.most_common(1)[0]
        owns.append(dict(email=e, kind="File", key=f, score=round(v / tot, 3)))
    return owns


def blame_cause(root, sha, file, old_ranges, max_ranges=3):
    """SZZ-lite: the commit that most often introduced the lines a fix removed/changed."""
    cnt, meta = Counter(), {}
    for a, b in old_ranges[:max_ranges]:
        out = git(root, "blame", "--porcelain", "-L", f"{a},{b}", f"{sha}^", "--", file)
        cur = None
        for line in out.splitlines():
            if re.match(r"^[0-9a-f]{40} ", line):
                cur = line.split()[0]
                cnt[cur] += 1
                meta.setdefault(cur, {})
            elif cur and line.startswith("author-mail "):
                meta[cur]["email"] = line.split(" ", 1)[1].strip().strip("<>").lower()
            elif cur and line.startswith("author "):
                meta[cur]["author"] = line[7:]
            elif cur and line.startswith("author-time "):
                meta[cur]["ts"] = int(line.split()[1])
            elif cur and line.startswith("summary "):
                meta[cur]["msg"] = line[8:]
    if not cnt:
        return None
    c, n = cnt.most_common(1)[0]
    return dict(sha=c, votes=n, total=sum(cnt.values()), **meta[c])
