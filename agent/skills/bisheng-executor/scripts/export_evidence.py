#!/usr/bin/env python3
"""Deterministic local review-bundle collector for AscendNPU-IR iterations.

Only reads a source Git repository and explicitly specified evidence paths.
Never runs build commands, changes Git index, sends network traffic, or pushes.
The produced bundle stays on the local filesystem until a human reviews it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
TEXT_EXTENSIONS = {
    ".txt", ".log", ".json", ".jsonl", ".md", ".csv", ".tsv",
    ".yaml", ".yml", ".xml", ".sh", ".ll", ".ir", ".bcmlir",
    ".stderr", ".stdout", ".diff", ".patch", ".rst", ".ini"
}
FORBIDDEN_PARTS = {
    ".git", ".ssh", ".aws", ".gnupg", "secrets", "credentials",
    "private_keys", "node_modules", "__pycache__", ".conda", "token"
}
FORBIDDEN_NAMES = {
    ".env", ".credentials.json", "id_rsa", "id_ed25519", "auth.json",
    "models.json", "config.json.bak", "kubeconfig"
}
PATCH_LIMIT_BYTES = 32 * 1024 * 1024


class ExportError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(repo: Path, *args: str, allow_nonzero: bool = False) -> subprocess.CompletedProcess[bytes]:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if not allow_nonzero and p.returncode:
        raise ExportError(f"git {' '.join(args)} failed rc={p.returncode}: {p.stderr[:500].decode(errors='replace')}")
    return p


def git_text(repo: Path, *args: str) -> str:
    return git(repo, *args).stdout.decode("utf-8", errors="replace").strip()


def valid_commit(repo: Path, revision: str) -> str:
    # Resolve SHA via Git, never by interpolating into a shell command.
    p = git(repo, "rev-parse", "--verify", revision + "^{commit}")
    return p.stdout.decode().strip()


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", older, newer, allow_nonzero=True).returncode == 0


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def ensure_safe_out(path: Path, repo: Path, evidence_paths: list[Path]) -> None:
    if path.exists() or path.is_symlink():
        raise ExportError(f"output exists; refusing to overwrite: {path}")
    if is_within(path, repo):
        raise ExportError("output must be outside source Git repository")
    if path == Path("/"):
        raise ExportError("refusing filesystem root as output")
    for ev in evidence_paths:
        if is_within(path, ev) or is_within(ev, path):
            raise ExportError("output and input evidence paths must not contain one another")


def sensitive_path(path: Path) -> bool:
    lower_parts = [x.lower() for x in path.parts]
    if any(part in FORBIDDEN_PARTS for part in lower_parts):
        return True
    if path.name.lower() in FORBIDDEN_NAMES:
        return True
    if path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
        return True
    return False


def resolve_tracked_or_untracked(repo: Path, rel: str) -> Path:
    candidate = repo / rel
    if candidate.is_symlink():
        raise ExportError(f"untracked symlink not permitted: {rel}")
    real = candidate.resolve(strict=True)
    if not is_within(real, repo):
        raise ExportError(f"untracked path escapes repository: {rel}")
    if not real.is_file():
        raise ExportError(f"untracked path is not a file: {rel}")
    if sensitive_path(Path(rel)):
        raise ExportError(f"untracked path is sensitive: {rel}")
    return real


def safe_git_diff(repo: Path, *args: str) -> bytes:
    p = git(repo, "diff", "--no-ext-diff", "--binary", *args)
    if len(p.stdout) > PATCH_LIMIT_BYTES:
        raise ExportError(f"Git diff exceeded {PATCH_LIMIT_BYTES // (1024 * 1024)} MiB; split task")
    return p.stdout


def list_untracked(repo: Path) -> list[str]:
    return sorted(x.decode("utf-8", errors="surrogateescape") for x in
                  git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout.split(b"\0") if x)


def make_untracked_patch(repo: Path, requested: list[str], known: set[str], max_text_bytes: int) -> tuple[bytes, list[str]]:
    out: list[bytes] = []
    included: list[str] = []
    for name in sorted(set(requested)):
        if name not in known:
            raise ExportError(f"--untracked path is not currently untracked: {name}")
        path = resolve_tracked_or_untracked(repo, name)
        if path.stat().st_size > max_text_bytes or b"\0" in path.read_bytes()[:4096]:
            raise ExportError(f"untracked non-text/oversized file, do not pack automatically: {name}")
        p = git(repo, "diff", "--no-index", "--binary", "--", "/dev/null", name, allow_nonzero=True)
        if p.returncode != 1:
            raise ExportError(f"untracked diff failed for {name}: rc={p.returncode}: {p.stderr[:150]!r}")
        out.append(p.stdout)
        included.append(name)
    joined = b"\n".join(out)
    if len(joined) > PATCH_LIMIT_BYTES:
        raise ExportError("untracked patch exceeds limit")
    return joined, included


def files_in_evidence(path: Path):
    if path.is_symlink():
        raise ExportError(f"symlink evidence input denied: {path}")
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise ExportError(f"evidence input missing: {path}")
    for root, dirs, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        dirs[:] = sorted(d for d in dirs if not (root_path / d).is_symlink() and not sensitive_path(Path(d)))
        for name in sorted(files):
            f = root_path / name
            if not f.is_symlink():
                yield f


def add_evidence(repo: Path, out: Path, inputs: list[Path], allowed_roots: list[Path],
                 max_file_bytes: int, max_total_bytes: int, max_files: int) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    copied_bytes = 0
    count = 0
    accepted_roots = [repo] + allowed_roots
    for idx, given in enumerate(inputs):
        if given.is_symlink():
            raise ExportError(f"symlink evidence input denied: {given}")
        inp = given.resolve(strict=True)
        roots = [r for r in accepted_roots if is_within(inp, r)]
        if not roots:
            raise ExportError(f"evidence outside repo and --allow-root: {inp}")
        base = max(roots, key=lambda x: len(x.parts))
        for f in files_in_evidence(inp):
            count += 1
            if count > max_files:
                raise ExportError(f"evidence file count exceeds {max_files}; narrow --evidence")
            if f.is_symlink():
                warnings.append(f"symlink omitted: {f}")
                continue
            real = f.resolve(strict=True)
            if not is_within(real, base) or real in seen:
                continue
            seen.add(real)
            relative = real.relative_to(base)
            if sensitive_path(relative):
                warnings.append(f"sensitive path omitted: {relative}")
                continue
            st = real.stat()
            if not real.is_file():
                continue
            record = {
                "source": str(real), "relative_under_allowed_root": str(relative),
                "size_bytes": st.st_size, "sha256": sha256_file(real), "copied": False,
                "kind": "text" if real.suffix.lower() in TEXT_EXTENSIONS else "binary_or_unclassified"
            }
            if record["kind"] == "text":
                if st.st_size > max_file_bytes:
                    record["reason"] = "exceeds per-file copy limit"
                    warnings.append(f"oversized text not copied: {real}")
                elif copied_bytes + st.st_size > max_total_bytes:
                    record["reason"] = "exceeds total copy limit"
                    warnings.append(f"text not copied, total size limit: {real}")
                elif b"\0" in real.open("rb").read(4096):
                    record["reason"] = "NUL byte detected"
                    warnings.append(f"non-text contents not copied: {real}")
                else:
                    target = out / "evidence" / f"root-{idx + 1:02d}" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(real, target)
                    record["copied"] = True
                    record["bundle_path"] = str(target.relative_to(out))
                    copied_bytes += st.st_size
            records.append(record)
    return records, warnings


def archive_bundle(out: Path) -> Path:
    archive = out.with_suffix(".zip")
    if archive.exists():
        raise ExportError(f"archive already exists: {archive}")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(x for x in out.rglob("*") if x.is_file()):
            entry = zipfile.ZipInfo(str(Path(out.name) / path.relative_to(out)), (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            z.writestr(entry, path.read_bytes())
    return archive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--task-file", type=Path, required=True)
    ap.add_argument("--report-file", type=Path, help="Human-written task report to include before computing SHA256SUMS")
    ap.add_argument("--task-start", required=True, help="Git commit that was HEAD when this task was authorized")
    ap.add_argument("--frozen", type=Path, required=True, help="P0 frozen.json produced by freeze_baseline.py")
    ap.add_argument("--out", type=Path, required=True, help="New local directory outside the source repo")
    ap.add_argument("--evidence", type=Path, action="append", default=[], help="Explicit file/dir for evidence; repeatable")
    ap.add_argument("--allow-root", type=Path, action="append", default=[], help="Approved evidence root outside repo")
    ap.add_argument("--untracked", action="append", default=[], help="Explicit untracked source file to include as patch")
    ap.add_argument("--max-text-mb", type=int, default=16)
    ap.add_argument("--max-total-mb", type=int, default=120)
    ap.add_argument("--max-files", type=int, default=500)
    ap.add_argument("--archive", action="store_true", help="Create a local ZIP; does not upload")
    args = ap.parse_args()
    try:
        if not TASK_ID_RE.fullmatch(args.task_id):
            raise ExportError("invalid task-id; use alphanumeric, underscore, hyphen, dot")
        if min(args.max_text_mb, args.max_total_mb, args.max_files) <= 0:
            raise ExportError("size and count bounds must be positive")
        repo = Path(args.repo).expanduser().resolve(strict=True)
        if not repo.is_dir() or repo != Path(git_text(repo, "rev-parse", "--show-toplevel")).resolve():
            raise ExportError("--repo must point to the Git toplevel")
        task = args.task_file.expanduser().resolve(strict=True)
        if not task.is_file() or task.is_symlink():
            raise ExportError("task file must be a real readable file")
        frozen = args.frozen.expanduser().resolve(strict=True)
        if not frozen.is_file() or frozen.is_symlink():
            raise ExportError("frozen file must be a real readable JSON")
        task_text = task.read_text(encoding="utf-8")
        fz = json.loads(frozen.read_text(encoding="utf-8"))
        if fz.get("status") != "PASS" or not fz.get("base_sha") or not fz.get("head_sha"):
            raise ExportError("P0 frozen baseline not PASS or SHA missing")
        base_sha = valid_commit(repo, fz["base_sha"])
        original_head = valid_commit(repo, fz["head_sha"])
        start_sha = valid_commit(repo, args.task_start)
        task_sha_matches = re.findall(
            r"(?im)^\s*(?:[-*#]\s*)?TASK_START_SHA\s*:\s*`?([0-9a-fA-F]{40})`?\s*$", task_text)
        if task_sha_matches:
            if len(task_sha_matches) != 1 or task_sha_matches[0].lower() != start_sha:
                raise ExportError("task file TASK_START_SHA does not match --task-start")
        elif not (args.task_id.upper().startswith("P0") and
                  re.search(r"(?im)TASK_START_SHA\s*:\s*AUTO_DISCOVER\s*$", task_text)):
            raise ExportError("task file must contain one exact TASK_START_SHA (P0 may use AUTO_DISCOVER)")
        task_ids = re.findall(r"(?im)^\s*(?:[-*#]\s*)?TASK_ID\s*:\s*`?([A-Za-z0-9_.-]+)`?\s*$", task_text)
        if task_ids and (len(task_ids) != 1 or task_ids[0] != args.task_id):
            raise ExportError("task file TASK_ID does not match --task-id")
        final_head = git_text(repo, "rev-parse", "HEAD")
        if re.search(r"(?im)TASK_START_SHA\s*:\s*AUTO_DISCOVER\s*$", task_text) and start_sha != original_head:
            raise ExportError("P0 AUTO_DISCOVER must use frozen head SHA as task start")
        if not is_ancestor(repo, base_sha, original_head):
            raise ExportError("frozen base is not ancestor of frozen head")
        if not is_ancestor(repo, original_head, start_sha):
            raise ExportError("task start is not descended from frozen head")
        if not is_ancestor(repo, start_sha, final_head):
            raise ExportError("current HEAD is not descendant of the task-start SHA")
        out = args.out.expanduser().resolve(strict=False)
        evidence_inputs = [p.expanduser().absolute() for p in args.evidence]
        allow_roots = [p.expanduser().resolve(strict=True) for p in args.allow_root]
        if any(r == Path("/") for r in allow_roots):
            raise ExportError("--allow-root / is forbidden; use a specific evidence directory")
        if any(not r.is_dir() for r in allow_roots):
            raise ExportError("--allow-root must name directories")
        ensure_safe_out(out, repo, evidence_inputs)
        out.parent.mkdir(parents=True, exist_ok=True)
        # mkdir is the only write before the local collection starts.
        out.mkdir()
        try:
            (out / "patches").mkdir()
            (out / "git").mkdir()
            shutil.copyfile(task, out / "task.md")
            shutil.copyfile(frozen, out / "git" / "frozen.json")
            status = git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
            (out / "git" / "status.txt").write_bytes(status)
            (out / "git" / "commits.txt").write_bytes(git(repo, "log", "--format=%H %P %s", "--reverse", base_sha + ".." + final_head).stdout)
            (out / "git" / "changed-paths.txt").write_bytes(git(repo, "diff", "--name-status", base_sha, "--").stdout)
            (out / "git" / "submodules.txt").write_bytes(git(repo, "submodule", "status", allow_nonzero=True).stdout)
            (out / "patches" / "from-task-start.patch").write_bytes(safe_git_diff(repo, start_sha, "--"))
            (out / "patches" / "from-frozen-base.patch").write_bytes(safe_git_diff(repo, base_sha, "--"))
            untracked = list_untracked(repo)
            untracked_patch, included_untracked = make_untracked_patch(
                repo, args.untracked, set(untracked), args.max_text_mb * 1024 * 1024)
            (out / "patches" / "untracked-selected.patch").write_bytes(untracked_patch)
            (out / "git" / "untracked-all.json").write_text(json.dumps(untracked, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            diff_check = git(repo, "diff", "--check", base_sha, allow_nonzero=True)
            (out / "git" / "diff-check.txt").write_bytes(diff_check.stdout + diff_check.stderr)
            (out / "git" / "task-start.sha").write_text(start_sha + "\n")
            (out / "git" / "final-head.sha").write_text(final_head + "\n")
            records, warnings = add_evidence(repo, out, evidence_inputs, allow_roots,
                                             args.max_text_mb * 1024 * 1024,
                                             args.max_total_mb * 1024 * 1024, args.max_files)
            omitted_untracked = sorted(set(untracked) - set(included_untracked))
            if omitted_untracked:
                warnings.append(f"{len(omitted_untracked)} untracked files not in source patch; examine untracked-all.json")
            if diff_check.returncode:
                warnings.append("git diff --check reports errors; see git/diff-check.txt")
            if not records:
                warnings.append("no evidence --evidence selected; source-only round or missing test artifacts")
            if not args.report_file:
                warnings.append("no human-written --report-file supplied; generated report is only a blank template")
            info = {
                "schema": "bisheng-review-bundle/1.0", "collection": "LOCAL_ONLY_NOT_APPROVED_FOR_EXTERNAL_TRANSFER",
                "collected_utc": datetime.now(timezone.utc).isoformat(),
                "task_id": args.task_id, "task_file_original": str(task),
                "repo": str(repo), "branch": git_text(repo, "branch", "--show-current"),
                "base_sha": base_sha, "frozen_head_sha": original_head,
                "task_start_sha": start_sha, "final_head_sha": final_head,
                "source_patch_includes": "tracked staged+unstaged changes since task start, plus commits",
                "untracked_included": included_untracked, "untracked_omitted": omitted_untracked,
                "dirty_worktree": bool(status), "diff_check_rc": diff_check.returncode,
                "evidence": records, "warnings": warnings,
                "collection_status": "COLLECTED_WITH_WARNINGS" if warnings else "COLLECTED",
                "gate_verdict": "NOT_EVALUATED_BY_EXPORTER",
                "external_transfer": "MANUAL_APPROVAL_REQUIRED; check patches, logs, and file paths for proprietary information and credentials"
            }
            write_json(out / "manifest.json", info)
            if args.report_file:
                report = args.report_file.expanduser().resolve(strict=True)
                if report.is_symlink() or not report.is_file() or report == task:
                    raise ExportError("--report-file must be a distinct regular text file")
                shutil.copyfile(report, out / "REPORT_FOR_REVIEW.md")
            else:
                (out / "REPORT_FOR_REVIEW.md").write_text(
                    "# Pi 执行轮次证据包\n\n"
                    f"- TASK_ID: `{args.task_id}`\n- BASE_SHA: `{base_sha}`\n"
                    f"- TASK_START_SHA: `{start_sha}`\n- FINAL_HEAD: `{final_head}`\n"
                    f"- COLLECTOR: `{info['collection_status']}`（不是代码或 E2E 验收 PASS）\n"
                    "- GATE_VERDICT: 待人工复审\n\n"
                    "## 此轮完成了什么（由 Pi 填写，不得猜测）\n\n"
                    "## 命令与真实退出码（由 Pi 填写，逐项引用证据）\n\n"
                    "## 失败与未执行项（由 Pi 填写）\n\n"
                    "## 请外部审查者重点检查（由 Pi 填写）\n\n"
                    "## 数据出域审批\n\n文件仅在本地生成。外发前必须人工审查和取得公司授权。\n",
                    encoding="utf-8")
            checks = []
            for file in sorted(f for f in out.rglob("*") if f.is_file()):
                checks.append(f"{sha256_file(file)}  {file.relative_to(out)}")
            (out / "SHA256SUMS.txt").write_text("\n".join(checks) + "\n", encoding="utf-8")
        except Exception:
            # Do not delete a partially collected local bundle; preserve it for diagnostics.
            raise
        archive = archive_bundle(out) if args.archive else None
        print(json.dumps({"result": "COLLECTED", "directory": str(out),
                          "archive": str(archive) if archive else None,
                          "archive_sha256": sha256_file(archive) if archive else None,
                          "manifest": str(out / "manifest.json"), "warnings": warnings},
                         ensure_ascii=False, indent=2))
        return 0
    except (ExportError, OSError, json.JSONDecodeError, ValueError) as exc:
        print("EXPORT_FAILED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
