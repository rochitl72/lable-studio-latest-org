# One-click launch (Mac)

## Desktop & Dock (recommended)

**`RBG Annotation Studio.app`** should be on your **Desktop** and in the **Dock**.

- **Desktop (home screen):** double-click `RBG Annotation Studio` on the Desktop  
- **Dock:** click the same icon in the Dock  

To re-pin after moving the project folder:

```bash
cd ~/Downloads/lableRBG/annoforge
./scripts/pin-to-dock-and-desktop.sh
```

## Or use the `.command` file

1. Open Finder → `Downloads/lableRBG/annoforge/`
2. Double-click **`Start RBG Annotation Studio.command`**
3. Terminal opens, servers start, **Safari/Chrome opens** to http://localhost:5173
4. You can **close the Terminal window** — the app keeps running

## Double-click to stop

**`Stop RBG Annotation Studio.command`**

## First launch only

The first time may take **5–15 minutes** (Python packages + SAM model download). Later launches are ~10 seconds.

## Your data (always local)

| Item | Path |
|------|------|
| Database | `backend/annoforge.db` |
| Images | `backend/storage/` |
| Logs | `logs/` |

Copy the whole `annoforge` folder to back up or move to another Mac.

## If macOS blocks the `.command` file

Right-click → **Open** → **Open** (first time only),  
or run in Terminal:

```bash
cd ~/Downloads/lableRBG/annoforge
chmod +x "Start RBG Annotation Studio.command"
./scripts/start-annoforge.sh
```

## Optional: Dock shortcut

Drag **`Start RBG Annotation Studio.command`** to the Dock (right side) for a one-click icon.
