#!/usr/bin/env python3
"""
Version bumping script for snowflake-sql-api-async.
Follows semantic versioning and creates tagged commits.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Tuple

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # fallback for older Python


class VersionBumper:
    def __init__(self, pyproject_path: Path = None):
        self.pyproject_path = pyproject_path or Path("pyproject.toml")
        if not self.pyproject_path.exists():
            raise FileNotFoundError(f"pyproject.toml not found at {self.pyproject_path}")

    def get_current_version(self) -> str:
        """Get the current version from pyproject.toml."""
        with open(self.pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]

    def parse_version(self, version: str) -> Tuple[int, int, int]:
        """Parse semantic version string into components."""
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-.*)?$", version)
        if not match:
            raise ValueError(f"Invalid version format: {version}")
        return tuple(map(int, match.groups()))

    def bump_version(self, bump_type: str) -> str:
        """Bump version based on type (major, minor, patch)."""
        current = self.get_current_version()
        major, minor, patch = self.parse_version(current)

        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        elif bump_type == "patch":
            return f"{major}.{minor}.{patch + 1}"
        else:
            raise ValueError(f"Invalid bump type: {bump_type}")

    def set_version(self, new_version: str) -> None:
        """Update version in pyproject.toml."""
        # Read current content
        content = self.pyproject_path.read_text()

        # Replace version line - handle both quoted and unquoted values
        patterns = [
            r'^version = "[^"]*"',  # version = "0.0.1"
            r"^version = '[^']*'",  # version = '0.0.1'
            r'^version = [^\s#]*',  # version = 0.0.1 (unquoted)
        ]

        replacement = f'version = "{new_version}"'
        new_content = content

        for pattern in patterns:
            new_content = re.sub(pattern, replacement, new_content, flags=re.MULTILINE)
            if new_content != content:
                break

        if content == new_content:
            # Debug: show what we're looking for
            print(f"Debug: Content around version line:")
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'version' in line and '=' in line:
                    print(f"  Line {i+1}: {repr(line)}")
            raise RuntimeError("Failed to update version in pyproject.toml")

        # Write back
        self.pyproject_path.write_text(new_content)
        print(f"✅ Updated version to {new_version} in pyproject.toml")

    def run_command(self, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a shell command."""
        print(f"🔧 Running: {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if check and result.returncode != 0:
            print(f"❌ Command failed: {cmd}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            sys.exit(1)

        return result

    def check_git_status(self) -> None:
        """Check if git working directory is clean."""
        result = self.run_command("git status --porcelain", check=False)
        if result.stdout.strip():
            print("❌ Git working directory is not clean.")
            print("Please commit or stash changes before bumping version.")
            sys.exit(1)

    def check_git_branch(self) -> str:
        """Get current git branch."""
        result = self.run_command("git branch --show-current")
        return result.stdout.strip()

    def create_version_commit(self, version: str, push: bool = True) -> None:
        """Create a commit and tag for the new version."""
        # Stage the pyproject.toml change
        self.run_command(f"git add {self.pyproject_path}")

        # Create commit
        commit_msg = f"bump: version {version}"
        self.run_command(f'git commit -m "{commit_msg}"')
        print(f"✅ Created commit: {commit_msg}")

        # Create tag
        tag_name = f"v{version}"
        self.run_command(f'git tag -a {tag_name} -m "Release {version}"')
        print(f"✅ Created tag: {tag_name}")

        if push:
            branch = self.check_git_branch()
            self.run_command(f"git push origin {branch}")
            self.run_command(f"git push origin {tag_name}")
            print(f"✅ Pushed to origin/{branch} and pushed tag {tag_name}")

    def bump_and_tag(self, bump_type: str = None, version: str = None,
                     push: bool = True, dry_run: bool = False) -> str:
        """Main function to bump version and create tag."""
        current_version = self.get_current_version()

        if version:
            # Validate custom version format
            self.parse_version(version)
            new_version = version
        elif bump_type:
            new_version = self.bump_version(bump_type)
        else:
            raise ValueError("Must specify either bump_type or version")

        print(f"📦 Current version: {current_version}")
        print(f"📦 New version: {new_version}")

        if dry_run:
            print("🔍 Dry run - no changes made")
            return new_version

        # Pre-flight checks
        self.check_git_status()

        # Update version
        self.set_version(new_version)

        # Create commit and tag
        self.create_version_commit(new_version, push=push)

        return new_version


def main():
    parser = argparse.ArgumentParser(
        description="Bump version and create tagged commit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/bump_version.py patch          # 1.0.0 -> 1.0.1
  python scripts/bump_version.py minor          # 1.0.1 -> 1.1.0  
  python scripts/bump_version.py major          # 1.1.0 -> 2.0.0
  python scripts/bump_version.py --version 1.5.0  # Set specific version
  python scripts/bump_version.py patch --dry-run   # Preview changes
  python scripts/bump_version.py patch --no-push   # Don't push to remote
        """
    )

    # Version specification (mutually exclusive)
    version_group = parser.add_mutually_exclusive_group(required=True)
    version_group.add_argument(
        "bump_type",
        nargs="?",
        choices=["major", "minor", "patch"],
        help="Type of version bump"
    )
    version_group.add_argument(
        "--version",
        help="Set specific version (e.g., 1.2.3)"
    )

    # Options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Don't push commit and tag to remote"
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help="Show current version and exit"
    )

    args = parser.parse_args()

    try:
        bumper = VersionBumper()

        if args.current:
            print(f"Current version: {bumper.get_current_version()}")
            return

        new_version = bumper.bump_and_tag(
            bump_type=args.bump_type,
            version=args.version,
            push=not args.no_push,
            dry_run=args.dry_run
        )

        if not args.dry_run:
            print(f"\n🎉 Successfully bumped to version {new_version}")
            print("Next steps:")
            print("  1. Wait for CI/CD to pass")
            print("  2. Run: python scripts/deploy.py")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


# Shortcuts for console scripts
def patch_shortcut():
    """Shortcut for patch version bump."""
    import sys
    sys.argv = [sys.argv[0], "patch"]
    main()

def minor_shortcut():
    """Shortcut for minor version bump."""
    import sys
    sys.argv = [sys.argv[0], "minor"]
    main()

def major_shortcut():
    """Shortcut for major version bump."""
    import sys
    sys.argv = [sys.argv[0], "major"]
    main()


if __name__ == "__main__":
    main()