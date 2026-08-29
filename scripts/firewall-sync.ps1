$ErrorActionPreference = "Stop"
$ruleName = "Swarm Agent API 8443"
$apiUrl = "http://127.0.0.1:8000/v1/agents"
try {
    $agents = @(Invoke-RestMethod -Uri $apiUrl -Method Get -TimeoutSec 10)
    $allowed = @($agents | Where-Object { $_.id -ne "master" -and $_.status -eq "online" } | ForEach-Object { $_.ip_allowlist } | Where-Object { $_ -and $_ -notin @("Any", "0.0.0.0/0", "::/0") } | Sort-Object -Unique)
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($allowed.Count -gt 0) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 -RemoteAddress $allowed -Profile Any | Out-Null
        Write-Output ("Allowed: " + ($allowed -join ","))
    } else {
        Write-Output "No approved agent IPs; port 8443 is not allowed by Swarm rule"
    }
} catch {
    Write-Error $_
    exit 1
}
