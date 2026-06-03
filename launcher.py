import json
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse
import urllib.error
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
EDITOR_DIR = BASE_DIR / "editor"
SCENES_DIR = BASE_DIR / "scenes"
VERSION_FILE = BASE_DIR / ".launcher-version"
TEMP_ZIP = BASE_DIR / "_temp_studio.zip"
TEMP_EXTRACT = BASE_DIR / "_temp_extract"


def load_config() -> dict:
    """Load config.json and return an empty config when repo_zip_url is not set."""
    if not CONFIG_PATH.exists():
        return {}

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    repo_zip_url = config.get("repo_zip_url", "")
    if not repo_zip_url or repo_zip_url == "PASTE_YOUR_GITHUB_ZIP_URL_HERE":
        return {}

    return config


def build_zip_url(repo_url: str) -> str:
    """Convert GitHub repo page URLs into direct ZIP download URLs."""
    if not repo_url:
        return ""

    url = repo_url.strip()
    if url.lower().endswith(".zip"):
        return url

    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return url

    path = parsed.path.strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return url

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    branch = "main"
    if len(parts) >= 4 and parts[2] == "tree":
        branch = parts[3]

    return f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"


def get_stored_version_url() -> str:
    """Get the URL of the last downloaded version."""
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return ""


def save_version_url(url: str) -> None:
    """Save the current version URL."""
    VERSION_FILE.write_text(url, encoding="utf-8")


USED_DURING_UPDATES_DIR = BASE_DIR / "usedDuringUpdates"


def backup_editor_projects() -> None:
    """Move existing editor projects into the update staging folder."""
    source = EDITOR_DIR / "projects"
    if not source.exists():
        return

    if USED_DURING_UPDATES_DIR.exists():
        shutil.rmtree(USED_DURING_UPDATES_DIR)

    shutil.move(str(source), str(USED_DURING_UPDATES_DIR))


def restore_editor_projects() -> None:
    """Restore preserved projects into the updated editor."""
    if not USED_DURING_UPDATES_DIR.exists():
        return

    target = EDITOR_DIR / "projects"
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    shutil.move(str(USED_DURING_UPDATES_DIR), str(target))


def download_and_extract(repo_zip_url: str) -> None:
    """Download zip from GitHub and extract to editor folder."""
    repo_zip_url = build_zip_url(repo_zip_url)
    print(f"Downloading PythonStudio from {repo_zip_url}...")

    try:
        urllib.request.urlretrieve(repo_zip_url, TEMP_ZIP)
    except urllib.error.HTTPError as e:
        if repo_zip_url.endswith("/main.zip"):
            alt_url = repo_zip_url[:-8] + "/master.zip"
            print("Main branch ZIP failed, trying master branch...")
            try:
                urllib.request.urlretrieve(alt_url, TEMP_ZIP)
                repo_zip_url = alt_url
            except Exception:
                raise RuntimeError(f"Failed to download {repo_zip_url}: {e}")
        else:
            raise RuntimeError(f"Failed to download {repo_zip_url}: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to download {repo_zip_url}: {e}")
    
    print("Extracting files...")
    try:
        if TEMP_EXTRACT.exists():
            shutil.rmtree(TEMP_EXTRACT)
        
        TEMP_EXTRACT.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(TEMP_ZIP, "r") as zip_ref:
            zip_ref.extractall(TEMP_EXTRACT)
        
        # Find the root folder in the extracted zip
        extracted_items = list(TEMP_EXTRACT.iterdir())
        if not extracted_items:
            raise RuntimeError("Downloaded zip was empty")
        
        # GitHub zips usually have a root folder like 'repo-main', extract from there
        extracted_root = extracted_items[0]

        # Preserve existing editor projects during update
        if EDITOR_DIR.exists():
            backup_editor_projects()

        # Remove old editor folder
        if EDITOR_DIR.exists():
            shutil.rmtree(EDITOR_DIR)

        # Create editor folder and move contents
        EDITOR_DIR.mkdir(parents=True, exist_ok=True)

        # Move all files from extracted root into editor folder
        for item in extracted_root.iterdir():
            dest = EDITOR_DIR / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))

        # Restore preserved projects into the updated editor
        restore_editor_projects()

        # Cleanup
        shutil.rmtree(TEMP_EXTRACT)
        TEMP_ZIP.unlink(missing_ok=True)

        # Save version URL
        save_version_url(repo_zip_url)

        print("Files extracted to editor folder")
    except Exception as e:
        raise RuntimeError(f"Failed to extract files: {e}")


def find_main_editor() -> Path:
    """Find the main_editor.py file inside the extracted editor folder."""
    matches = list(EDITOR_DIR.rglob("main_editor.py"))
    if not matches:
        raise FileNotFoundError(f"main_editor.py not found under {EDITOR_DIR}")
    return matches[0]


def start_studio() -> None:
    """Start the editor."""
    editor_main = find_main_editor()
    print(f"Starting PythonStudio from {editor_main}...")
    subprocess.run([sys.executable, str(editor_main)], cwd=str(editor_main.parent), check=False)


def main() -> None:
    try:
        config = load_config()
        repo_zip_url = config.get("repo_zip_url", "")
        repo_zip_url = build_zip_url(repo_zip_url) if repo_zip_url else ""

        if EDITOR_DIR.exists():
            stored_url = get_stored_version_url()
            if repo_zip_url and stored_url != repo_zip_url:
                print("New version detected. Updating editor...")
                download_and_extract(repo_zip_url)
            else:
                print("PythonStudio editor found. Starting...")
        else:
            if repo_zip_url:
                print("PythonStudio editor not found. Setting up...")
                download_and_extract(repo_zip_url)
            else:
                raise ValueError(
                    "Editor not found and repo_zip_url is not configured in config.json. "
                    "Set repo_zip_url to a GitHub repo or ZIP URL."
                )

        start_studio()

    except Exception as error:
        print(f"Error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
