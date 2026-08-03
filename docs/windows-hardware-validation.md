# Windows 11 hardware validation checklist

Use this checklist for the first physical Windows test. It deliberately separates automated
packaging evidence from the Wi-Fi-driver and privacy behavior that a hosted CI runner cannot prove.
Do not include your Wi-Fi password in any report.

## Record the test environment

Open a normal PowerShell window and run:

```powershell
winver
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture
Get-NetAdapter | Where-Object InterfaceDescription -Match 'Wireless|Wi-Fi|802.11' |
    Format-Table Name, InterfaceDescription, Status, LinkSpeed
Get-Service WlanSvc | Format-List Name, Status, StartType
```

Record the Windows edition/build, x64 or ARM64, laptop model, and Wi-Fi adapter description. The
current beta artifact is x86-64.

## Permission behavior

- [ ] Start with **Settings → Privacy & security → Location → Let desktop apps access your
  location** disabled.
- [ ] Attempt a scan and confirm the application reports a Windows location-access error rather
  than crashing or saving a blank point.
- [ ] Use **Request Location Access** and confirm the correct Windows Settings page opens.
- [ ] Enable Location services and desktop-app access, then return without using Administrator.
- [ ] Scan again and note whether Windows displayed a one-time consent prompt.
- [ ] Confirm the scan succeeds after permission is granted.

## Reading correctness

- [ ] At least one normal SSID is visible rather than every reading being `<hidden>`.
- [ ] BSSIDs use six uppercase colon-separated bytes, for example `AA:BB:CC:DD:EE:FF`.
- [ ] RSSI values are plausible negative dBm values (commonly around `-30` to `-90`).
- [ ] A known 2.4 GHz access point has the expected channel and `2.4 GHz` band.
- [ ] A known 5 GHz access point has the expected channel and `5 GHz` band.
- [ ] If 6 GHz hardware is available, its channel and `6 GHz` band are correct; otherwise record
  this item as not tested rather than failed.
- [ ] Compare a few readings with the Windows taskbar network list or another trusted survey tool.
  Do not use `netsh` output as application input.

## Survey workflow

- [ ] Load a non-square floor plan and complete two-point metre calibration.
- [ ] Zoom and pan without accidentally creating a sample.
- [ ] Capture at least five points at least one metre apart.
- [ ] Confirm each marker appears and hovering shows readings.
- [ ] Select SSID, BSSID, and band filters independently and obtain an eligible heatmap.
- [ ] Save a `.wifisurvey`, quit with Alt+F4, reopen it, and continue sampling.
- [ ] Open the Windows-saved survey on macOS and a macOS-saved survey on Windows.
- [ ] Start a scan and close the application; confirm it exits without needing Task Manager.

## Diagnostics and report

Run **WiFi Site Survey Diagnostics.exe** from the extracted beta folder. It should show a successful
count and band summary without printing SSIDs or BSSIDs.

Please report results in this compact form:

```text
Windows edition/build:
Architecture:
Laptop and Wi-Fi adapter:
Location-denied behavior: pass/fail + message
Location-granted behavior: pass/fail
One-time prompt appeared: yes/no
2.4 GHz channel check:
5 GHz channel check:
6 GHz channel check: pass/fail/not tested
Five-point scan and heatmap: pass/fail
Save/reopen: pass/fail
macOS exchange: pass/fail/not tested
Normal exit / exit during scan: pass/fail
Diagnostics summary:
Other observations:
```

Screenshots may contain private SSIDs, BSSIDs, usernames, or floor plans. Crop or redact them before
sharing. The public release remains blocked until the critical permission, scan, and exit checks
pass on real Windows 11 Wi-Fi hardware.
