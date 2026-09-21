import argparse
import importlib
import os
import re
import subprocess
import sys
from datetime import datetime

from apps.app.core.db import session_factory

RESERVED_VERBS = {"generate", "create", "-h", "--help"}
SEED_DIR = os.path.join("database", "seed")
SEED_PACKAGE = "database.seed"


SEED_SUFFIX = "_seed"


def _slugify(service_name):
  slug = service_name.strip().lower()
  slug = re.sub(r"[\s-]+", "_", slug)
  slug = re.sub(r"[^a-z0-9_]", "", slug)
  slug = re.sub(r"_+", "_", slug).strip("_")
  return slug or "seed"


def _seed_filename_slug(service_name):
  slug = _slugify(service_name)
  return slug if slug.endswith(SEED_SUFFIX) else f"{slug}{SEED_SUFFIX}"


def _format_with_black(seed_dir):
  venv_python = os.path.join(os.path.dirname(sys.executable), "python.exe")
  if not os.path.exists(venv_python):
    venv_python = sys.executable
  result = subprocess.run(
    [venv_python, "-m", "black", seed_dir],
    capture_output=True,
    text=True,
  )
  if result.returncode != 0:
    print(f"\n⚠️  black formatting failed:\n{result.stderr}")


def generate_seed(service_name):
  os.makedirs(SEED_DIR, exist_ok=True)
  slug = _seed_filename_slug(service_name)
  path = os.path.join(SEED_DIR, f"{slug}.py")

  if os.path.exists(path):
    print(f"\n❌ {path} already exists. Pick a different name or edit it directly.")
    sys.exit(1)

  content = f'''"""{service_name}

Create Date: {datetime.now().isoformat()}

"""
from sqlalchemy.orm import Session


def main(session: Session) -> None:
  """Run this seed.

  The runner owns the session/transaction: use `session` for all writes,
  never call session.commit()/session.rollback() here.
  """
  pass
'''
  with open(path, "w", encoding="utf-8") as f:
    f.write(content)

  _format_with_black(SEED_DIR)
  print(f"Generating {path} ...  done")
  sys.exit(0)


def run_seed_by_name(service_name):
  slug = _seed_filename_slug(service_name)
  path = os.path.join(SEED_DIR, f"{slug}.py")

  if not os.path.exists(path):
    print(f"\n❌ No seed named '{service_name}' - expected {path}. Use 'generate' to create it.")
    sys.exit(1)

  module = importlib.import_module(f"{SEED_PACKAGE}.{slug}")

  session = session_factory()
  try:
    module.main(session)
    session.commit()
    print(f"\n✅ Seed '{service_name}' completed successfully.")
  except Exception as error:
    session.rollback()
    print(f"\n❌ Seed '{service_name}' ({path}) failed: {error}")
    sys.exit(1)
  finally:
    session.close()


def build_parser():
  parser = argparse.ArgumentParser(prog="python -m run.seed")
  subparsers = parser.add_subparsers(dest="command", required=True)

  generate_p = subparsers.add_parser("generate", help="Create a new seed file")
  generate_p.add_argument("service_name")

  create_p = subparsers.add_parser("create", help="Alias for 'generate'")
  create_p.add_argument("service_name")

  return parser


def main():
  if len(sys.argv) > 1 and sys.argv[1] not in RESERVED_VERBS:
    run_seed_by_name(" ".join(sys.argv[1:]))
    return

  args = build_parser().parse_args()

  if args.command in ("generate", "create"):
    generate_seed(args.service_name)


if __name__ == "__main__":
  main()
