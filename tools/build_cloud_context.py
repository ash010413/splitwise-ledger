"""Create an allowlisted build context; never upload the checkout or local data."""

import argparse
import shutil
from pathlib import Path


def prepare(destination):
    root = Path(__file__).resolve().parents[1]
    destination = Path(destination).resolve()
    if destination == root or root in destination.parents:
        raise ValueError("Use a separate temporary directory for the cloud build")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Build directory must be empty")
    for name in ["Dockerfile", "pyproject.toml", "requirements-cloud.lock"]:
        shutil.copyfile(root / name, destination / name)
    shutil.copytree(
        root / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    (destination / "deploy/gcp").mkdir(parents=True)
    shutil.copyfile(root / "deploy/gcp/cloudbuild.yaml", destination / "deploy/gcp/cloudbuild.yaml")
    print("Prepared allowlisted cloud build context; credentials and local data excluded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    prepare(parser.parse_args().destination)
