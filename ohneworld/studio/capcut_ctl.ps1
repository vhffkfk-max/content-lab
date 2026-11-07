# 캡컷 창 조작 도우미. 캡컷 창이 맨 앞에 있는 것을 확인한 뒤에만 클릭·키를 보낸다 (다른 창에 입력이 들어가지 않게).
#   powershell -File capcut_ctl.ps1 bgshot <저장경로>          앞으로 가져오지 않고 캡컷 창 찍기 (기본으로 이것을 쓴다)
#   powershell -File capcut_ctl.ps1 bgclick <x> <y> [double]   커서를 옮기지 않고 클릭 메시지만 보내기
#   powershell -File capcut_ctl.ps1 busy                       사용자가 캡컷을 쓰는 중인지
#   아래 shot·click·key 는 캡컷을 맨 앞으로 가져와 사용자를 방해하므로 쓰지 않는다 (2026-11-06 사용자 요청)
#   powershell -File capcut_ctl.ps1 shot <저장경로>            캡컷 창만 찍기 (창 위치도 출력)
#   powershell -File capcut_ctl.ps1 click <x> <y> [double]     창 안 좌표(찍은 그림 기준) 클릭
#   powershell -File capcut_ctl.ps1 key <SendKeys 글자>         예: " " (재생/멈춤)
#   powershell -File capcut_ctl.ps1 close                      정상 종료 요청 후 끝날 때까지 기다림
#   powershell -File capcut_ctl.ps1 open                       실행하고 창이 뜰 때까지 기다림
param([string]$cmd, [string]$a1, [string]$a2, [string]$a3)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(int f, int x, int y, int d, int e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, int f, int e);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr ChildWindowFromPointEx(IntPtr h, POINT p, uint f);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
$exe = "$env:LOCALAPPDATA\CapCut\Apps\CapCut.exe"

function Win { Get-Process CapCut -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1 }

function Front($p) {
  $h = $p.MainWindowHandle
  if ([W]::IsIconic($h)) { [void][W]::ShowWindow($h, 9) }
  for ($i = 0; $i -lt 5; $i++) {
    [W]::keybd_event(0x12, 0, 0, 0); [W]::keybd_event(0x12, 0, 2, 0)   # Alt 를 눌렀다 떼면 맨 앞으로 가져오기가 허용된다
    [void][W]::SetForegroundWindow($h); Start-Sleep -Milliseconds 300
    if ([W]::GetForegroundWindow() -eq $h) { return $true }
  }
  return $false
}

function Rect($p) { $r = New-Object W+RECT; [void][W]::GetWindowRect($p.MainWindowHandle, [ref]$r); return $r }

switch ($cmd) {
  "open" {
    # 열어도 사용자가 쓰던 창을 다시 앞으로 돌려놓는다 (캡컷이 앞을 가로채지 않게)
    $prev = [W]::GetForegroundWindow()
    if (-not (Win)) { Start-Process $exe }
    for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; if (Win) { break } }
    Start-Sleep -Milliseconds 800
    if ($prev -ne [IntPtr]::Zero -and [W]::GetForegroundWindow() -ne $prev) { [W]::keybd_event(0x12, 0, 0, 0); [W]::keybd_event(0x12, 0, 2, 0); [void][W]::SetForegroundWindow($prev) }
    if (Win) { "열림" } else { "창이 안 뜸"; exit 1 }
  }
  "busy" {
    # 사용자가 지금 캡컷을 보고 있나 (캡컷 창이 맨 앞이면 busy)
    $p = Win; if ($p -and [W]::GetForegroundWindow() -eq $p.MainWindowHandle) { "busy"; exit 1 } else { "free"; exit 0 }
  }
  "close" {
    $p = Win
    if (-not $p) { "이미 꺼짐"; exit 0 }
    # 편집 화면을 닫으면 첫 화면으로 돌아가므로 몇 번 닫는다 (캡컷이 스스로 저장한다)
    for ($k = 0; $k -lt 4; $k++) {
      $p = Win; if (-not $p) { break }
      [void]$p.CloseMainWindow()
      for ($i = 0; $i -lt 16; $i++) { Start-Sleep -Milliseconds 500; $q = Win; if (-not $q -or $q.MainWindowHandle -ne $p.MainWindowHandle) { break } }
    }
    for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Milliseconds 500; if (-not (Get-Process CapCut -ErrorAction SilentlyContinue)) { "꺼짐"; exit 0 } }
    "아직 안 꺼짐 (저장 확인 창 등)"; exit 1
  }
  "shot" {
    $p = Win; if (-not $p) { "캡컷 없음"; exit 1 }
    if (-not (Front $p)) { "캡컷을 맨 앞으로 못 가져옴"; exit 1 }
    Start-Sleep -Milliseconds 400
    $r = Rect $p; $w = $r.R - $r.L; $hh = $r.B - $r.T
    $bmp = New-Object System.Drawing.Bitmap $w, $hh
    [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size $w, $hh))
    $bmp.Save($a1); "창 $($r.L),$($r.T) 크기 ${w}x${hh}"
  }
  "bgshot" {
    # 앞으로 가져오지 않고 창 내용만 찍는다 (사용자 작업을 방해하지 않음). 최소화돼 있으면 못 찍는다
    $p = Win; if (-not $p) { "캡컷 없음"; exit 1 }
    if ([W]::IsIconic($p.MainWindowHandle)) { "최소화돼 있어 못 찍음"; exit 1 }
    $r = Rect $p; $w = $r.R - $r.L; $hh = $r.B - $r.T
    $bmp = New-Object System.Drawing.Bitmap $w, $hh
    $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
    $ok = [W]::PrintWindow($p.MainWindowHandle, $dc, 2); $g.ReleaseHdc($dc)
    $bmp.Save($a1); "찍음 $ok ${w}x${hh}"
  }
  "bgclick" {
    # 커서를 옮기지 않고 창에 클릭 메시지만 보낸다 (앞으로 가져오지 않음). 앱에 따라 안 먹을 수 있다
    $p = Win; if (-not $p) { "캡컷 없음"; exit 1 }
    $l = [IntPtr](([int]$a2 -shl 16) -bor ([int]$a1 -band 0xFFFF))
    [void][W]::PostMessage($p.MainWindowHandle, 0x0200, [IntPtr]0, $l)
    [void][W]::PostMessage($p.MainWindowHandle, 0x0201, [IntPtr]1, $l); Start-Sleep -Milliseconds 60
    [void][W]::PostMessage($p.MainWindowHandle, 0x0202, [IntPtr]0, $l)
    if ($a3 -eq "double") { Start-Sleep -Milliseconds 60; [void][W]::PostMessage($p.MainWindowHandle, 0x0203, [IntPtr]1, $l); [void][W]::PostMessage($p.MainWindowHandle, 0x0202, [IntPtr]0, $l) }
    "보냄 $a1,$a2"
  }
  "click" {
    $p = Win; if (-not $p) { "캡컷 없음"; exit 1 }
    if (-not (Front $p)) { "캡컷을 맨 앞으로 못 가져옴, 클릭 안 함"; exit 1 }
    $r = Rect $p; $x = $r.L + [int]$a1; $y = $r.T + [int]$a2
    [void][W]::SetCursorPos($x, $y); Start-Sleep -Milliseconds 120
    $n = if ($a3 -eq "double") { 2 } else { 1 }
    for ($i = 0; $i -lt $n; $i++) { [W]::mouse_event(2, 0, 0, 0, 0); [W]::mouse_event(4, 0, 0, 0, 0); Start-Sleep -Milliseconds 90 }
    "클릭 $x,$y"
  }
  "key" {
    $p = Win; if (-not $p) { "캡컷 없음"; exit 1 }
    if (-not (Front $p)) { "캡컷을 맨 앞으로 못 가져옴, 키 안 보냄"; exit 1 }
    [System.Windows.Forms.SendKeys]::SendWait($a1); "키 보냄"
  }
}
