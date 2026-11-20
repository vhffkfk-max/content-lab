# 안드로이드 '기타 파일' 찾기/정리 도구 (Windows + USB 디버깅)
# android_storage.bat 를 더블클릭해서 실행하세요.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = '안드로이드 기타 파일 정리'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SD = '/storage/emulated/0'
# 통째로 지우면 안 되는 폴더 (안에 들어가서 하위 폴더만 지울 수 있음)
$Protected = @($SD, "$SD/Android", "$SD/Android/data", "$SD/Android/obb", "$SD/Android/media")
$Personal = @('DCIM', 'Pictures', 'Movies', 'Music', 'Documents', 'Download', 'Recordings')

$KnownApps = @{
  'com.kakao.talk' = '카카오톡'; 'org.telegram.messenger' = '텔레그램'; 'org.telegram.messenger.web' = '텔레그램'
  'com.google.android.youtube' = '유튜브'; 'com.google.android.apps.youtube.music' = '유튜브 뮤직'
  'com.netflix.mediaclient' = '넷플릭스'; 'com.instagram.android' = '인스타그램'; 'com.facebook.katana' = '페이스북'
  'com.sec.android.app.sbrowser' = '삼성 인터넷'; 'com.android.chrome' = '크롬'; 'com.nhn.android.search' = '네이버'
  'com.iloen.melon' = '멜론'; 'com.spotify.music' = '스포티파이'; 'com.zhiliaoapp.musically' = '틱톡'
  'com.ss.android.ugc.trill' = '틱톡'; 'com.coupang.mobile' = '쿠팡'; 'com.discord' = '디스코드'
  'com.whatsapp' = '왓츠앱'; 'jp.naver.line.android' = '라인'; 'com.google.android.apps.photos' = '구글 포토'
  'com.samsung.android.app.notes' = '삼성 노트'; 'com.sec.android.gallery3d' = '갤러리'
  'com.tving.player' = '티빙'; 'kr.co.captv.pooqV2' = '웨이브'; 'com.coupang.mobile.play' = '쿠팡플레이'
  'com.disney.disneyplus' = '디즈니+'; 'com.naver.vapp' = '네이버 NOW/V'; 'com.nhn.android.webtoon' = '네이버 웹툰'
}

function Say([string]$t, [string]$c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Pause-Key { Write-Host ''; Read-Host '엔터를 누르면 계속' | Out-Null }
function Q([string]$p) { "'" + ($p -replace "'", "'\''") + "'" }
function Fmt([double]$kb) {
  if ($kb -ge 1048576) { return ('{0:N1} GB' -f ($kb / 1048576)) }
  if ($kb -ge 1024) { return ('{0:N0} MB' -f ($kb / 1024)) }
  return ('{0:N0} KB' -f $kb)
}
function AppName([string]$pkg) { if ($KnownApps.ContainsKey($pkg)) { return $KnownApps[$pkg] } return '' }

# ---------------- ADB 준비 ----------------
function Get-Adb {
  $local = Join-Path $Root 'platform-tools\adb.exe'
  if (Test-Path $local) { return $local }
  $cmd = Get-Command adb.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  Say 'ADB(폰 연결 도구)가 없어서 Google 공식 사이트에서 받는 중이에요... (약 10MB)' Yellow
  $zip = Join-Path $env:TEMP 'platform-tools-latest-windows.zip'
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $Root -Force
    Remove-Item $zip -ErrorAction SilentlyContinue
  } catch {
    Say "다운로드 실패: $($_.Exception.Message)" Red
    Say '인터넷 연결을 확인하거나, https://developer.android.com/tools/releases/platform-tools 에서' Yellow
    Say "Windows용 zip을 받아 압축을 풀고 platform-tools 폴더를 이 폴더($Root)에 넣어 주세요." Yellow
    Pause-Key; exit 1
  }
  return $local
}

function Sh([string]$cmd) { & $script:ADB shell $cmd 2>$null | ForEach-Object { "$_" } }

function Wait-Device {
  & $script:ADB start-server 2>$null | Out-Null
  $shown = ''
  while ($true) {
    $lines = @(& $script:ADB devices 2>$null | Select-Object -Skip 1 | Where-Object { "$_" -match '\S' } | ForEach-Object { "$_" })
    $ok = @($lines | Where-Object { $_ -match "\tdevice$" })
    if ($ok.Count -ge 1) {
      if ($ok.Count -gt 1) { Say '폰이 여러 대 연결돼 있어요. 정리할 폰 1대만 꽂아 주세요.' Red; Start-Sleep 3; continue }
      return
    }
    if ($lines -match 'unauthorized') { $msg = 'unauth' } else { $msg = 'none' }
    if ($msg -ne $shown) {
      $shown = $msg
      Clear-Host
      if ($msg -eq 'unauth') {
        Say '폰 화면에 "USB 디버깅을 허용하시겠습니까?" 창이 떠 있어요.' Yellow
        Say '  -> "이 컴퓨터에서 항상 허용" 체크 후 [허용]을 눌러 주세요.' Yellow
      } else {
        Say '폰이 아직 안 보여요. 아래를 확인해 주세요:' Yellow
        Say '  1. USB 케이블로 PC와 폰 연결 (충전 전용 케이블이면 안 돼요)'
        Say '  2. 설정 > 휴대전화 정보 > 소프트웨어 정보 > 빌드번호 7번 탭 (개발자 옵션 켜기)'
        Say '  3. 설정 > 개발자 옵션 > USB 디버깅 켜기'
        Say '  4. 폰에 뜨는 "USB 디버깅 허용" 창에서 [허용]'
      }
      Say "`n자동으로 다시 확인 중... (창을 닫으면 종료)" DarkGray
    }
    Start-Sleep 2
  }
}

# ---------------- 기능 ----------------
function Get-Children([string]$path) {
  foreach ($l in (Sh "du -k -d 1 $(Q $path) 2>/dev/null")) {
    if ($l -match '^(\d+)\s+(.+)$') { [pscustomobject]@{ KB = [int64]$Matches[1]; Path = $Matches[2].Trim() } }
  }
}

function Get-DataUsage {
  foreach ($l in (Sh 'df -k /data')) {
    if ($l -match '\s(\d+)\s+(\d+)\s+(\d+)\s+\d+%') { return [pscustomobject]@{ TotalKB = [int64]$Matches[1]; UsedKB = [int64]$Matches[2]; FreeKB = [int64]$Matches[3] } }
  }
}

function Get-AppSizes {
  $ds = (Sh 'dumpsys diskstats') -join "`n"
  function Arr([string]$name) {
    if ($ds -match ([regex]::Escape($name) + ': \[(.*?)\]')) { return @($Matches[1] -split ',' | ForEach-Object { $_.Trim().Trim('"') }) }
    return @()
  }
  $names = Arr 'Package Names'; $app = Arr 'App Sizes'; $data = Arr 'App Data Sizes'; $cache = Arr 'Cache Sizes'
  $list = for ($i = 0; $i -lt $names.Count; $i++) {
    $a = [int64]0; $d = [int64]0; $c = [int64]0
    if ($i -lt $app.Count) { [int64]::TryParse($app[$i], [ref]$a) | Out-Null }
    if ($i -lt $data.Count) { [int64]::TryParse($data[$i], [ref]$d) | Out-Null }
    if ($i -lt $cache.Count) { [int64]::TryParse($cache[$i], [ref]$c) | Out-Null }
    [pscustomobject]@{ Pkg = $names[$i]; AppKB = $a / 1024; DataKB = $d / 1024; CacheKB = $c / 1024; TotalKB = ($a + $d + $c) / 1024 }
  }
  $other = $null
  if ($ds -match 'Other Size: (\d+)') { $other = [int64]$Matches[1] / 1024 }
  return [pscustomobject]@{ Apps = @($list); OtherKB = $other }
}

function Show-Summary {
  Clear-Host
  Say '== 1. 전체 요약 ==' Cyan
  Say '계산 중... (1~3분 걸릴 수 있어요)' DarkGray
  $df = Get-DataUsage
  $sdKB = 0
  foreach ($l in (Sh "du -k -s $SD 2>/dev/null")) { if ($l -match '^(\d+)') { $sdKB = [int64]$Matches[1] } }
  $as = Get-AppSizes
  $appsKB = ($as.Apps | Measure-Object TotalKB -Sum).Sum
  Say ''
  if ($df) { Say ("폰 전체 사용량        : {0} / {1}  (남은 공간 {2})" -f (Fmt $df.UsedKB), (Fmt $df.TotalKB), (Fmt $df.FreeKB)) White }
  Say ("내장 메모리 폴더 합계 : {0}   <- 내 파일 앱에서 보이는 영역 (Android/data 포함)" -f (Fmt $sdKB)) White
  if ($appsKB) { Say ("앱 합계(앱+데이터+캐시): {0}   <- 휴대폰이 마지막으로 계산한 값" -f (Fmt $appsKB)) White }
  if ($as.OtherKB) { Say ("휴대폰이 계산한 '기타': {0}" -f (Fmt $as.OtherKB)) White }
  Say ''
  if ($sdKB -gt 20 * 1048576) {
    Say '-> 내장 메모리 폴더 안에 큰 용량이 있어요. 메뉴 2(폴더 탐색)로 어디인지 찾아보세요.' Green
  }
  if ($df -and $sdKB -and $appsKB -and ($df.UsedKB - $sdKB - $appsKB) -gt 30 * 1048576) {
    Say '-> 폴더/앱으로 설명 안 되는 용량이 커요. 시스템 계산 오류일 수 있어요:' Yellow
    Say '   폰 재부팅 -> 설정 > 애플리케이션 > (필터에서 시스템 앱 표시) > 미디어 저장소 > 저장공간 > 데이터 삭제 -> 재부팅' Yellow
  }
  Pause-Key
}

function Show-Apps {
  Clear-Host
  Say '== 4. 앱별 용량 순위 (상위 25) ==' Cyan
  $as = Get-AppSizes
  if ($as.Apps.Count -eq 0) { Say '앱 용량 정보를 가져오지 못했어요.' Red; Pause-Key; return }
  Say ('{0,-4}{1,-10}{2,-10}{3,-10}{4}' -f '#', '합계', '데이터', '캐시', '앱') DarkGray
  $i = 0
  foreach ($a in ($as.Apps | Sort-Object TotalKB -Descending | Select-Object -First 25)) {
    $i++
    $label = $a.Pkg; $n = AppName $a.Pkg; if ($n) { $label = "$n ($($a.Pkg))" }
    Say ('{0,-4}{1,-10}{2,-10}{3,-10}{4}' -f $i, (Fmt $a.TotalKB), (Fmt $a.DataKB), (Fmt $a.CacheKB), $label)
  }
  Say "`n데이터가 큰 앱은 폰에서 설정 > 애플리케이션 > 그 앱 > 저장공간 에서 정리하거나," DarkGray
  Say '앱 안의 설정(예: 텔레그램 캐시, 카카오톡 채팅방 미디어 정리)에서 지우는 게 가장 안전해요.' DarkGray
  Say '(이 값은 휴대폰이 하루 1번 정도 계산해 둔 값이라 약간 예전 값일 수 있어요)' DarkGray
  Pause-Key
}

function Confirm-Delete([string]$path, [int64]$kb) {
  if ($Protected -contains $path) {
    Say '이 폴더는 시스템 핵심 폴더라 통째로 지울 수 없어요. 안으로 들어가서 하위 폴더를 골라 주세요.' Red
    Pause-Key; return $false
  }
  Say ''
  Say "삭제 대상: $path  ($(Fmt $kb))" White
  $rel = $path.Substring([Math]::Min($SD.Length + 1, $path.Length))
  if ($path -like "$SD/Android/data/*" -or $path -like "$SD/Android/media/*" -or $path -like "$SD/Android/obb/*") {
    $pkg = ($rel -split '/')[2]; $n = AppName $pkg
    Say "주의: 앱 [$n $pkg] 의 데이터예요." Yellow
    Say '  지우면 그 앱의 오프라인 저장 영상/음악, 받은 사진·파일, 게임 추가 데이터가 사라질 수 있어요.' Yellow
    Say '  앱 자체와 계정은 남아요. 게임(obb)은 다시 실행하면 재다운로드해요.' Yellow
  } elseif ($Personal -contains ($rel -split '/')[0]) {
    Say '주의: 사진/동영상/다운로드 같은 개인 파일 폴더예요. 백업했는지 꼭 확인하세요! (휴지통 없이 바로 지워져요)' Red
  }
  $ans = Read-Host "정말 지우려면 yes 를 입력 (취소는 그냥 엔터)"
  return ($ans -eq 'yes')
}

function Remove-Remote([string]$path) {
  Say '삭제 중...' DarkGray
  Sh "rm -rf $(Q $path)" | Out-Null
  $left = Sh "ls -d $(Q $path) 2>/dev/null"
  if ($left) { Say '일부 또는 전체를 지우지 못했어요 (권한 제한). 해당 앱 안에서 지우거나 앱 설정에서 데이터 삭제를 해 주세요.' Red }
  else { Say '삭제 완료!' Green }
  Pause-Key
}

function Explore {
  $cur = $SD
  while ($true) {
    Clear-Host
    Say "== 2. 폴더 탐색 ==   현재 위치: $cur" Cyan
    Say '용량 계산 중... (큰 폴더는 1~2분 걸려요)' DarkGray
    $all = @(Get-Children $cur)
    $self = $all | Where-Object { $_.Path -eq $cur } | Select-Object -First 1
    $kids = @($all | Where-Object { $_.Path -ne $cur } | Sort-Object KB -Descending | Select-Object -First 40)
    Clear-Host
    Say "== 2. 폴더 탐색 ==   현재 위치: $cur" Cyan
    if ($self) {
      $sum = ($all | Where-Object { $_.Path -ne $cur } | Measure-Object KB -Sum).Sum
      Say ("이 폴더 전체: {0}   (이 폴더에 바로 들어있는 파일들: {1})" -f (Fmt $self.KB), (Fmt ([Math]::Max(0, $self.KB - $sum)))) White
    }
    Say ''
    $i = 0
    foreach ($k in $kids) {
      $i++
      $name = $k.Path.Substring($cur.Length).TrimStart('/')
      $n = AppName $name; if ($n) { $name = "$name  [$n]" }
      $color = 'Gray'; if ($k.KB -ge 1048576) { $color = 'Yellow' }; if ($k.KB -ge 10 * 1048576) { $color = 'Red' }
      Say ('{0,4}. {1,10}  {2}' -f $i, (Fmt $k.KB), $name) $color
    }
    if ($kids.Count -eq 0) { Say '(하위 폴더 없음)' DarkGray }
    Say "`n번호 = 그 폴더로 들어가기 | d 번호 = 그 폴더 삭제 (예: d 3) | b = 위로 | q = 메뉴로" DarkCyan
    $in = (Read-Host '선택').Trim()
    if ($in -eq 'q') { return }
    if ($in -eq 'b') { if ($cur -ne $SD) { $cur = $cur.Substring(0, $cur.LastIndexOf('/')) }; continue }
    if ($in -match '^d\s*(\d+)$') {
      $idx = [int]$Matches[1] - 1
      if ($idx -ge 0 -and $idx -lt $kids.Count) {
        if (Confirm-Delete $kids[$idx].Path $kids[$idx].KB) { Remove-Remote $kids[$idx].Path }
      }
      continue
    }
    if ($in -match '^\d+$') {
      $idx = [int]$in - 1
      if ($idx -ge 0 -and $idx -lt $kids.Count) { $cur = $kids[$idx].Path }
    }
  }
}

function Big-Files {
  while ($true) {
    Clear-Host
    Say '== 3. 큰 파일 찾기 (200MB 이상) ==' Cyan
    Say '찾는 중... (1~3분)' DarkGray
    $files = @(foreach ($l in (Sh "find $SD -type f -size +200M -exec du -k {} + 2>/dev/null")) {
      if ($l -match '^(\d+)\s+(.+)$') { [pscustomobject]@{ KB = [int64]$Matches[1]; Path = $Matches[2].Trim() } }
    } | Sort-Object KB -Descending | Select-Object -First 50)
    Clear-Host
    Say '== 3. 큰 파일 찾기 (200MB 이상) ==' Cyan
    if ($files.Count -eq 0) { Say '200MB 넘는 파일이 없어요.' Green; Pause-Key; return }
    $i = 0
    foreach ($f in $files) { $i++; Say ('{0,4}. {1,10}  {2}' -f $i, (Fmt $f.KB), $f.Path.Substring($SD.Length)) }
    Say "`nd 번호 = 그 파일 삭제 (예: d 2) | q = 메뉴로" DarkCyan
    $in = (Read-Host '선택').Trim()
    if ($in -match '^d\s*(\d+)$') {
      $idx = [int]$Matches[1] - 1
      if ($idx -ge 0 -and $idx -lt $files.Count -and (Confirm-Delete $files[$idx].Path $files[$idx].KB)) { Remove-Remote $files[$idx].Path }
      continue
    }
    return
  }
}

function Trim-Caches {
  Clear-Host
  Say '== 5. 모든 앱 캐시 정리 ==' Cyan
  Say '앱들이 임시로 쌓아 둔 캐시만 지워요. 사진, 채팅, 로그인 정보는 지워지지 않아요.' White
  Say '(앱을 처음 열 때 잠깐 느릴 수 있어요)' DarkGray
  $ans = Read-Host '진행하려면 yes 입력'
  if ($ans -ne 'yes') { return }
  $before = Get-DataUsage
  Sh 'pm trim-caches 9999G' | Out-Null
  Start-Sleep 2
  $after = Get-DataUsage
  if ($before -and $after) { Say ("정리 완료! 확보한 공간: {0}" -f (Fmt ([Math]::Max(0, $before.UsedKB - $after.UsedKB)))) Green }
  else { Say '정리 완료!' Green }
  Pause-Key
}

# ---------------- 메인 ----------------
try {
  $script:ADB = Get-Adb
  Wait-Device
  $model = (Sh 'getprop ro.product.model') -join ''
  while ($true) {
    Clear-Host
    Say '=========================================' Cyan
    Say '   안드로이드 기타 파일 찾기 / 정리 도구' Cyan
    Say "   연결된 폰: $model" Cyan
    Say '=========================================' Cyan
    $df = Get-DataUsage
    if ($df) { Say ("   사용 중 {0} / {1}  (남은 공간 {2})" -f (Fmt $df.UsedKB), (Fmt $df.TotalKB), (Fmt $df.FreeKB)) White }
    Say ''
    Say '  1. 전체 요약 (기타 파일이 어디쯤 있는지 진단)'
    Say '  2. 폴더 탐색 & 삭제  <- 기타 파일 찾는 핵심 기능'
    Say '  3. 큰 파일 찾기 (200MB 이상)'
    Say '  4. 앱별 용량 순위'
    Say '  5. 모든 앱 캐시 정리 (안전)'
    Say '  0. 종료'
    Say ''
    switch ((Read-Host '번호 선택').Trim()) {
      '1' { Show-Summary }
      '2' { Explore }
      '3' { Big-Files }
      '4' { Show-Apps }
      '5' { Trim-Caches }
      '0' { exit 0 }
    }
    Wait-Device
  }
} catch {
  Say "오류가 났어요: $($_.Exception.Message)" Red
  Pause-Key
}
