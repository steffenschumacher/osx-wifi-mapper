# Windows 11 guide

This guide assumes you have not used PowerShell, Git, Python, or `uv` before. WiFi Site Survey is
a normal desktop application and must be run as your signed-in Windows user. **Do not run it as
Administrator.** Administrator rights do not bypass Windows location privacy.

Windows support is currently developed on the `feature/windows-support` branch. Until a Windows
ZIP appears on the GitHub Releases page, use the source instructions below. A tagged public
Windows release will not be published until scanning has been verified on physical Windows 11
Wi-Fi hardware.

## Before starting: check the computer architecture

1. Open the Windows **Start** menu.
2. Select **Settings**.
3. Open **System → About**.
4. Find **System type** under **Device specifications**.

If it says **x64-based processor**, use the `windows-x86_64` download. If it says **ARM-based
processor**, do not use the x86-64 beta for validation unless Windows explicitly offers emulation;
there is not yet a native Windows ARM64 artifact.

## Running a downloaded release

These steps apply after a release contains `wifi-site-survey-windows-x86_64.zip`.

### 1. Download and verify it

Download these two files from the same GitHub release:

- `wifi-site-survey-windows-x86_64.zip`
- `wifi-site-survey-windows-x86_64.zip.sha256`

They normally appear in your **Downloads** folder. To verify that the ZIP arrived unchanged:

1. Open Start, type `PowerShell`, and select **Windows PowerShell**. Do not choose **Run as
   administrator**.
2. Copy the following command, paste it into the blue PowerShell window, and press Enter:

   ```powershell
   cd $HOME\Downloads
   Get-FileHash .\wifi-site-survey-windows-x86_64.zip -Algorithm SHA256
   Get-Content .\wifi-site-survey-windows-x86_64.zip.sha256
   ```

3. Compare the two long hexadecimal values. Letter case does not matter, but every character must
   otherwise match. Do not run the download if they differ.

### 2. Extract and start it

1. Open **File Explorer → Downloads**.
2. Right-click `wifi-site-survey-windows-x86_64.zip` and choose **Extract All…**.
3. Accept the suggested folder and select **Extract**.
4. Open the extracted **WiFi Site Survey** folder.
5. Double-click **WiFi Site Survey.exe**.

Keep the EXE in that folder. The adjacent `_internal` directory contains Python, Qt, and other
required libraries; moving only the EXE will break the application.

The current build is not Authenticode-signed because the project does not have a Windows code-
signing certificate. Windows SmartScreen may display **Windows protected your PC**. After verifying
the checksum and that the download came from this repository's release page, choose **More info**,
confirm the app name is WiFi Site Survey, then choose **Run anyway**. Do not disable SmartScreen or
antivirus globally. If antivirus quarantines a file, record the product name and detection and
report it rather than creating a broad exclusion.

## Allowing Wi-Fi scan access

Windows 11 treats nearby BSSIDs as precise-location information. A scan can fail with “access
denied” even though the app never asks for your GPS coordinates.

1. Open **Settings → Privacy & security → Location**.
2. Turn on **Location services**.
3. Turn on **Let apps access your location** if that option is shown.
4. Turn on **Let desktop apps access your location**.
5. Return to WiFi Site Survey. The **Request Location Access** button opens this Settings page.
6. Start a scan from a calibrated floor plan. Windows may show a one-time location consent prompt;
   approve it for scanning.

Depending on the Windows version and whether an application has an installed package identity,
Windows may list WiFi Site Survey under recent desktop activity rather than giving it an individual
toggle. The desktop-app master switch is therefore important.

## First survey

1. Start WiFi Site Survey.
2. Choose **Choose Floor Plan…** and select a PNG or JPEG image.
3. In the calibration dialog, click the two endpoints of a known straight distance.
4. Enter that real distance in metres and accept the calibration.
5. Stand at the corresponding location on the floor plan and make one stationary crosshair click.
6. Do not move or use other controls while the blue scanning banner is visible.
7. When the green completion banner says it is safe, walk to the next point.
8. Use **File → Save Survey…** to save a portable `.wifisurvey` file.

## Running from source

Use this method while Windows support remains on its feature branch.

### 1. Open a normal PowerShell window

Open Start, type `PowerShell`, and select **Windows PowerShell**. The prompt normally resembles:

```text
PS C:\Users\YourName>
```

All commands below are entered in that window, one block at a time. Do not use an Administrator
window.

### 2. Install Git

Windows 11 normally includes `winget`. Paste:

```powershell
winget install --id Git.Git -e --source winget
```

Close PowerShell when installation finishes, open it again, and confirm:

```powershell
git --version
```

If `winget` is unavailable, download **Git for Windows** from <https://git-scm.com/download/win>,
use its default installer choices, then reopen PowerShell.

### 3. Install uv

Use the official Windows installer command:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell, then check:

```powershell
uv --version
```

`uv` installs and manages the correct Python version for this project; you do not need to install
Python separately.

### 4. Download the feature branch

```powershell
cd $HOME
git clone https://github.com/steffenschumacher/osx-wifi-mapper.git
cd .\osx-wifi-mapper
git switch feature/windows-support
```

The first command chooses your user folder. The second downloads the repository. The third enters
that folder, and the fourth selects the Windows development branch.

### 5. Install dependencies and start the app

```powershell
uv sync --all-extras --locked
uv run wifi-site-survey-native
```

The first run downloads Python, PySide6/Qt, and scientific libraries, so it can take several
minutes. Later starts are faster. The app is native and does not start a web server, open a browser,
or require a Windows Firewall exception. Close it with **File → Quit**, the window's **X**, or
Alt+F4. In PowerShell, Ctrl+C can stop a source-launched process if its window becomes inaccessible.

To update this branch later:

```powershell
cd $HOME\osx-wifi-mapper
git pull --ff-only
uv sync --all-extras --locked
```

## Troubleshooting

Run these commands in a normal PowerShell window.

### Check the Wi-Fi adapter

```powershell
Get-NetAdapter | Where-Object InterfaceDescription -Match 'Wireless|Wi-Fi|802.11' |
    Format-Table Name, InterfaceDescription, Status
```

The adapter should say `Up`. Also ensure airplane mode is off and Wi-Fi is enabled in Quick
Settings.

### Check WLAN AutoConfig

```powershell
Get-Service WlanSvc | Format-List Name, Status, StartType
```

It should normally show `Running`. If it is stopped, open Start, type `Services`, open the Services
application, find **WLAN AutoConfig**, and start it. Managed work computers may require an IT
administrator to change service policy.

### “Windows denied access”

Recheck every switch under **Settings → Privacy & security → Location**, especially **Let desktop
apps access your location**. Do not relaunch as Administrator. Corporate privacy policy can disable
location access; in that case contact the organization's IT administrator.

### No networks or stale results

- Confirm Windows itself can display nearby networks from the taskbar Wi-Fi menu.
- Wait several seconds and try one more scan; drivers throttle scans differently.
- Disconnecting from the current network is not required.
- Update the Wi-Fi adapter driver through the laptop manufacturer's support tools or Windows Update.
- Report the adapter model, Windows version, and whether the taskbar sees networks. Do not post Wi-Fi
  passwords or exported wireless profiles.

### Capture source diagnostics

From the repository folder, run:

```powershell
uv run wifi-site-survey-native 2>&1 | Tee-Object -FilePath .\wifi-site-survey-debug.txt
```

Reproduce the failure, close the app, then inspect `wifi-site-survey-debug.txt` before sharing it.
The scanner does not read saved Wi-Fi passwords, but logs or screenshots can contain SSIDs and
BSSIDs. Redact those identifiers if they are private. Never run or share `netsh wlan export profile`
output; exported profiles can contain sensitive configuration.

The downloaded portable build also includes **WiFi Site Survey Diagnostics.exe**. Double-click it,
allow a scan, and read the console summary. It reports the operating system, scan success, access-
point count, and band counts but deliberately omits SSIDs and BSSIDs. Take a screenshot of an error
before pressing a key or closing the console.

## Removing the application

For the portable release, close the app and delete the extracted **WiFi Site Survey** folder. It
does not install a service or driver. You may also delete the downloaded ZIP and checksum file.

For a source checkout, close the app and delete the `osx-wifi-mapper` folder through File Explorer.
Python versions and caches managed by `uv` are shared with other projects and need not be removed.
