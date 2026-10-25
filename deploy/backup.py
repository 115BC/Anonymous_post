#!/usr/bin/env python3
"""SQLite 在线备份 + 30 天轮转。

示例：
    python deploy/backup.py
    python deploy/backup.py --db /var/lib/classsite/classsite.db --out /var/backups/classsite --keep-days 30

备份使用 SQLite backup API，运行中的站点无需停机。
备份文件包含反馈与树洞正文（但没有任何作者身份字段），请按班级内部资料保管。
"""

import argparse
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE / "instance" / "classsite.db"
DEFAULT_OUT = BASE / "instance" / "backups"
DEFAULT_UPLOADS = Path(os.environ.get("CLASSSITE_UPLOADS") or (BASE / "instance" / "uploads"))


def parse_args():
    parser = argparse.ArgumentParser(description="备份班级空间数据库并清理过期备份")
    parser.add_argument("--db", default=os.environ.get("CLASSSITE_DB") or DEFAULT_DB,
                        help="源数据库路径")
    parser.add_argument("--out", default=os.environ.get("CLASSSITE_BACKUP_DIR") or DEFAULT_OUT,
                        help="备份目录")
    parser.add_argument("--keep-days", type=int,
                        default=int(os.environ.get("BACKUP_KEEP_DAYS", "30")),
                        help="保留天数，0 表示不清理")
    parser.add_argument("--with-files", action="store_true",
                        help="同时把上传的资源文件打包为 zip")
    parser.add_argument("--uploads", default=str(DEFAULT_UPLOADS),
                        help="资源文件目录")
    return parser.parse_args()


def backup(db_path: Path, out_dir: Path, stamp: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"classsite-{stamp}.db"
    temp = final.with_suffix(".tmp")

    if temp.exists():
        temp.unlink()

    source = sqlite3.connect(str(db_path))
    try:
        target = sqlite3.connect(temp)
        try:
            source.backup(target)
            status = target.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            target.close()
    finally:
        source.close()

    if status != "ok":
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"备份完整性检查失败：{status}")

    temp.replace(final)
    try:
        os.chmod(final, 0o600)
    except OSError:
        pass
    return final


def backup_files(upload_dir: Path, out_dir: Path, stamp: str) -> Path | None:
    if not upload_dir.is_dir():
        return None
    if not any(path.is_file() for path in upload_dir.rglob("*")):
        return None
    final = out_dir / f"classsite-files-{stamp}.zip"
    temp_base = out_dir / f".classsite-files-{stamp}"
    temp_zip = temp_base.with_suffix(".zip")
    temp_zip.unlink(missing_ok=True)
    shutil.make_archive(str(temp_base), "zip", root_dir=str(upload_dir))
    temp_zip.replace(final)
    try:
        os.chmod(final, 0o600)
    except OSError:
        pass
    return final


def prune(out_dir: Path, keep_days: int) -> list[Path]:
    if keep_days <= 0:
        return []
    cutoff = time.time() - keep_days * 86400
    removed = []
    for pattern in ("classsite-*.db", "classsite-files-*.zip"):
        for path in out_dir.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed.append(path)
            except FileNotFoundError:
                pass
    return removed


def main():
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = BASE / db_path
    if not db_path.exists():
        sys.exit(f"找不到数据库：{db_path}")

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = BASE / out_dir

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final = backup(db_path, out_dir, stamp)
    print(f"已备份数据库：{final}（{final.stat().st_size} 字节）")

    if args.with_files:
        uploads = Path(args.uploads)
        if not uploads.is_absolute():
            uploads = BASE / uploads
        files_backup = backup_files(uploads, out_dir, stamp)
        if files_backup:
            print(f"已备份资源文件：{files_backup}（{files_backup.stat().st_size} 字节）")
        else:
            print("资源目录为空或不存在，跳过文件备份。")

    for old in prune(out_dir, args.keep_days):
        print(f"已删除过期备份：{old}")


if __name__ == "__main__":
    main()
