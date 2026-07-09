# run_daily_daemon.ps1
$workingDir = "D:\podcast_creator"
Set-Location $workingDir

$pythonPath = "D:\podcast_creator\podcastCreator\Scripts\python.exe"
$scriptPath = "D:\podcast_creator\main.py"
$logPath = "D:\podcast_creator\daily_daemon.log"

$maxRetries = 5
$retryCount = 0
$backoffSeconds = 300 # 5 minutes

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Starting daily-daemon wrapper..." | Out-File -FilePath $logPath -Append -Encoding utf8

while ($true) {
    # Run python and redirect stdout and stderr to the log file in UTF-8 in real-time
    & $pythonPath -u $scriptPath daily-daemon 2>&1 | Out-File -FilePath $logPath -Append -Encoding utf8
    $exitCode = $LastExitCode
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] daily-daemon exited with code $exitCode" | Out-File -FilePath $logPath -Append -Encoding utf8
    
    if ($exitCode -eq 0) {
        # Successful exit (e.g., stopped by user or finished normally)
        break
    }
    
    # It failed
    $retryCount++
    if ($retryCount -gt $maxRetries) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "[$timestamp] Maximum retries ($maxRetries) reached. Daemon wrapper exiting." | Out-File -FilePath $logPath -Append -Encoding utf8
        
        # Load PresentationFramework to show MessageBox
        Add-Type -AssemblyName PresentationFramework
        $msg = "The Podcast Creator daily-daemon failed repeatedly and reached the maximum retry limit.`n`nPlease check the log file at:`n$logPath"
        [System.Windows.MessageBox]::Show($msg, "Podcast Creator Daemon Failed", "OK", "Error")
        exit $exitCode
    }
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] Attempt $retryCount/$maxRetries failed. Retrying in $($backoffSeconds) seconds..." | Out-File -FilePath $logPath -Append -Encoding utf8
    Start-Sleep -Seconds $backoffSeconds
}
