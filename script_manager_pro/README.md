# Script Manager Pro

A Blender add-on for managing and running external Python scripts with one-click access, favorites, tags, and in-panel metadata editing.

![Blender](https://img.shields.io/badge/Blender-4.4%2B-orange)
![Version](https://img.shields.io/badge/Version-0.0.3-blue)
![License](https://img.shields.io/badge/License-GPL--3.0-green)

## Features

- **One-Click Script Execution** - Run any Python script directly from the sidebar panel
- **Open in Text Editor** - Quickly open scripts in Blender's built-in text editor
- **Favorites** - Mark frequently used scripts for quick access and filter by favorites
- **Custom Tags** - Add tags to scripts for categorization and filtering
- **Custom Display Names** - Set friendly names for your scripts
- **In-Panel Editing** - Edit script metadata (tags, display name) without leaving the panel
- **Persistent Metadata** - All favorites, tags, and display names are saved across sessions
- **Open Scripts Folder** - Quick access to your scripts directory from the panel

## Installation

### As Blender Extension (Recommended)
1. Download the latest release `.zip`
2. In Blender, go to **Edit > Preferences > Get Extensions**
3. Click the dropdown arrow and select **Install from Disk**
4. Select the downloaded `.zip` file

### Manual Installation
1. Clone or download this repository
2. Copy the `script_manager_pro` folder to your Blender extensions directory

## Setup

1. After installation, go to **Edit > Preferences > Add-ons**
2. Find **Script Manager Pro** and expand it
3. Set the **Scripts Folder Path** to the directory containing your Python scripts
4. Open the **3D Viewport** sidebar (press `N`) and find the **Script Manager** tab

## Usage

1. Click **Refresh List** to scan your scripts folder
2. Each script appears with action buttons:
   - **Play** - Execute the script
   - **Text** - Open in Blender's text editor
   - **Star** - Toggle favorite status
   - **Pencil** - Edit metadata (display name, tags)
3. Use the **Tags** filter to find scripts by tag
4. Toggle **Favorites** to show only starred scripts

## Project Structure

```
script_manager_pro/
├── __init__.py              # Main add-on code
├── blender_manifest.toml    # Blender extension manifest
└── README.md
```

## Permissions

| Permission | Reason |
|------------|--------|
| `files` | Reads and writes script metadata to a JSON file |

## Requirements

- Blender 4.4.0 or later
- No external Python dependencies

## License

[GPL-3.0-or-later](https://www.gnu.org/licenses/gpl-3.0.html)

## Author

**Cemil Berk** - [cemilbnr](https://github.com/cemilbnr)
