#!/usr/bin/env python3
"""
Deployment script for snowflake-sql-api-async package.
Handles building and uploading to PyPI/TestPyPI.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # fallback for older Python


class PackageDeployer:
    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.pyproject_path = self.project_root / "pyproject.toml"
        self.dist_dir = self.project_root / "dist"

        if not self.pyproject_path.exists():
            raise FileNotFoundError(f"pyproject.toml not found at {self.pyproject_path}")

    def get_package_info(self) -> dict:
        """Get package information from pyproject.toml."""
        with open(self.pyproject_path, "rb") as f:
            data = tomllib.load(f)

        project = data["project"]
        return {
            "name": project["name"],
            "version": project["version"],
            "description": project.get("description", ""),
        }

    def run_command(self, cmd: str, check: bool = True, cwd: Path = None) -> subprocess.CompletedProcess:
        """Run a shell command."""
        run_cwd = cwd or self.project_root
        print(f"🔧 Running: {cmd} (in {run_cwd})")

        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=run_cwd
        )

        if check and result.returncode != 0:
            print(f"❌ Command failed: {cmd}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            sys.exit(1)

        return result

    def check_prerequisites(self) -> None:
        """Check if required tools are available."""
        print("🔍 Checking prerequisites...")

        required_commands = ["python", "twine"]
        for cmd in required_commands:
            result = self.run_command(f"command -v {cmd}", check=False)
            if result.returncode != 0:
                print(f"❌ {cmd} not found. Please install it first.")
                if cmd == "twine":
                    print("   Install with: pip install twine")
                sys.exit(1)
            print(f"  ✅ {cmd} found")

    def check_git_status(self) -> None:
        """Verify git repository is clean and up to date."""
        print("🔍 Checking git status...")

        # Check if working directory is clean
        result = self.run_command("git status --porcelain", check=False)
        if result.stdout.strip():
            print("⚠️  Git working directory has uncommitted changes")
            uncommitted = result.stdout.strip().split('\n')
            for line in uncommitted[:5]:  # Show first 5 changes
                print(f"   {line}")
            if len(uncommitted) > 5:
                print(f"   ... and {len(uncommitted) - 5} more")

            response = input("Continue anyway? (y/N): ")
            if response.lower() != 'y':
                sys.exit(1)

        # Check if we're ahead of remote
        result = self.run_command("git status -b --porcelain", check=False)
        if "ahead" in result.stdout:
            print("⚠️  Local branch is ahead of remote")
            response = input("Continue without pushing? (y/N): ")
            if response.lower() != 'y':
                sys.exit(1)

    def clean_build_artifacts(self) -> None:
        """Remove previous build artifacts."""
        print("🧹 Cleaning build artifacts...")

        patterns_to_clean = [
            "dist",
            "build",
            "*.egg-info",
            "**/*.pyc",
            "**/__pycache__"
        ]

        for pattern in patterns_to_clean:
            for path in self.project_root.glob(pattern):
                if path.is_dir():
                    shutil.rmtree(path)
                    print(f"  🗑️  Removed directory: {path.name}")
                elif path.is_file():
                    path.unlink()
                    print(f"  🗑️  Removed file: {path.name}")

    def build_package(self) -> None:
        """Build the package using python -m build."""
        print("🏗️  Building package...")
        self.run_command("python -m build")

        # Verify build artifacts exist
        if not self.dist_dir.exists() or not list(self.dist_dir.glob("*")):
            raise RuntimeError("Build failed - no artifacts in dist/")

        artifacts = list(self.dist_dir.glob("*"))
        print("  ✅ Build completed. Artifacts:")
        for artifact in artifacts:
            print(f"     📦 {artifact.name}")

    def check_package(self) -> None:
        """Check the built package using twine."""
        print("🔍 Checking package integrity...")
        self.run_command("twine check dist/*")
        print("  ✅ Package check passed")

    def upload_to_repository(self, repository: str = "pypi") -> None:
        """Upload package to specified repository."""
        repo_urls = {
            "testpypi": "https://test.pypi.org/legacy/",
            "pypi": "https://upload.pypi.org/legacy/"
        }

        print(f"📤 Uploading to {repository.upper()}...")

        if repository == "testpypi":
            self.run_command("twine upload --repository testpypi dist/*")
        else:
            self.run_command("twine upload dist/*")

        print(f"  ✅ Successfully uploaded to {repository.upper()}")

    def get_install_command(self, repository: str, package_name: str) -> str:
        """Get the pip install command for testing."""
        if repository == "testpypi":
            return f"pip install --index-url https://test.pypi.org/simple/ {package_name}"
        else:
            return f"pip install {package_name}"

    def deploy(self, test_only: bool = False, skip_test: bool = False,
               skip_build: bool = False, force: bool = False) -> None:
        """Main deployment function."""
        package_info = self.get_package_info()

        print("🚀 Starting deployment process...")
        print(f"📦 Package: {package_info['name']} v{package_info['version']}")
        print(f"📝 Description: {package_info['description']}")

        # Pre-flight checks
        self.check_prerequisites()

        if not force:
            self.check_git_status()

        # Build process
        if not skip_build:
            self.clean_build_artifacts()
            self.build_package()
            self.check_package()
        else:
            print("⏭️  Skipping build (using existing dist/)")
            if not self.dist_dir.exists() or not list(self.dist_dir.glob("*")):
                raise RuntimeError("No build artifacts found in dist/")

        # Upload process
        if not skip_test:
            self.upload_to_repository("testpypi")
            print("\n🧪 TestPyPI upload complete!")
            test_cmd = self.get_install_command("testpypi", package_info['name'])
            print(f"   Test with: {test_cmd}")

            if not test_only:
                print("\n" + "="*50)
                response = input("Upload to production PyPI? (y/N): ")
                if response.lower() == 'y':
                    self.upload_to_repository("pypi")
                    print("\n🎉 Production deployment complete!")
                    install_cmd = self.get_install_command("pypi", package_info['name'])
                    print(f"   Install with: {install_cmd}")
                else:
                    print("⏹️  Deployment stopped at TestPyPI")
        else:
            # Skip test, go directly to PyPI
            if not force:
                print("⚠️  Uploading directly to production PyPI!")
                response = input("Are you sure? (y/N): ")
                if response.lower() != 'y':
                    print("❌ Deployment cancelled")
                    return

            self.upload_to_repository("pypi")
            print("🎉 Production deployment complete!")


def main():
    parser = argparse.ArgumentParser(
        description="Deploy snowflake-sql-api-async to PyPI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/deploy.py                # Full deployment (TestPyPI → PyPI)
  python scripts/deploy.py --test-only    # Only deploy to TestPyPI
  python scripts/deploy.py --skip-test    # Skip TestPyPI, go to PyPI
  python scripts/deploy.py --skip-build   # Use existing build artifacts
  python scripts/deploy.py --force        # Skip safety checks
        """
    )

    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Only upload to TestPyPI"
    )
    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="Skip TestPyPI and upload directly to PyPI"
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building and use existing dist/ artifacts"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip safety checks (git status, confirmations)"
    )

    args = parser.parse_args()

    try:
        deployer = PackageDeployer()
        deployer.deploy(
            test_only=args.test_only,
            skip_test=args.skip_test,
            skip_build=args.skip_build,
            force=args.force
        )

    except KeyboardInterrupt:
        print("\n❌ Deployment cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()