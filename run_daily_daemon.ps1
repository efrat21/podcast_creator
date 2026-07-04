# run_daily_daemon.ps1
$workingDir = "D:\podcast_creator"
Set-Location $workingDir

$pythonPath = "D:\podcast_creator\podcastCreator\Scripts\python.exe"
$scriptPath = "D:\podcast_creator\main.py"
$logPath = "D:\podcast_creator\daily_daemon.log"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Starting daily-daemon wrapper..." | Out-File -FilePath $logPath -Append -Encoding utf8

# Run python and redirect stdout and stderr to the log file in UTF-8 in real-time
& $pythonPath -u $scriptPath daily-daemon 2>&1 | Out-File -FilePath $logPath -Append -Encoding utf8

$exitCode = $LastExitCode
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] daily-daemon exited with code $exitCode" | Out-File -FilePath $logPath -Append -Encoding utf8

# Check if the process exited with a non-zero code (indicates failure)
if ($exitCode -ne 0) {
    # Load PresentationFramework to show MessageBox
    Add-Type -AssemblyName PresentationFramework
    $msg = "The Podcast Creator daily-daemon failed with exit code $exitCode.`n`nPlease check the log file at:`n$logPath"
    [System.Windows.MessageBox]::Show($msg, "Podcast Creator Daemon Failed", "OK", "Error")
}
