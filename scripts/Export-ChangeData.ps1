<#
.SYNOPSIS
    Read-only export of the change requests, incidents, change approvals and the business service map from ServiceNow, written as the
    CSV files that changecal reads.

.DESCRIPTION
    Only GET requests to the ServiceNow Table API. Nothing is created, changed or deleted. No credential is written to disk: the user is
    asked for with Get-Credential (basic authentication) and kept in memory, or an OAuth access token is passed as a SecureString.
    A user with read access to the tables below is enough (for example the itil role, plus read access to the CMDB tables).

    Every call is GET https://<instance>.service-now.com/api/now/table/<table> with:
      sysparm_query                   the encoded query (filters below)
      sysparm_fields                  only the columns changecal needs
      sysparm_display_value=true      choice labels (Normal, Scheduled, 2 - High, Successful with issues) and the names of referenced
                                      records (CI, group, user, change number) instead of sys_ids
      sysparm_exclude_reference_link=true
      sysparm_limit and sysparm_offset paging: the offset grows by the limit until a page comes back shorter than the limit.
    Dates come in the time zone and format of the API user: set the user's date format to yyyy-MM-dd and time to HH:mm:ss.

      - changes.csv:     table change_request, planned start from the first day of the oldest month in the trend to -HorizonDays
                         ahead (start_date), ordered by start_date. Fields: number, short_description, type, state, risk, impact,
                         cmdb_ci, business_service, assignment_group, assigned_to, requested_by, opened_at, start_date, end_date,
                         work_start, work_end, approval, cab_date, close_code, backout_plan, test_plan, implementation_plan,
                         justification, outside_maintenance_schedule, review_status, review_date.
      - incidents.csv:   table incident, opened since the same date. Fields: number, short_description, priority, state, opened_at,
                         resolved_at, cmdb_ci, business_service, assignment_group, caused_by (the 'Caused by Change' reference).
      - approvals.csv:   table sysapproval_approver for change requests (sysapproval.sys_class_name=change_request) updated since the
                         same date. Fields: sysapproval (the change number), approver, state, sys_updated_on.
      - ci-services.csv: table cmdb_ci_service (name, busines_criticality - the field name is spelt that way - owned_by, support_group)
                         and table cmdb_rel_ci, relationships of type 'Depends on::Used by' whose parent is a service: a child that is
                         another service becomes a dependency (service_depends_on), any other child becomes a CI of the service.

    Not exported, because it lives elsewhere or differs between instances: freezes.csv (the freeze and blackout register: copy it from
    your blackout schedules or the change calendar; see docs/data-format.md) and settings.json.

.PARAMETER Instance
    The instance name or URL: contoso or https://contoso.service-now.com.

.PARAMETER TrendMonths
    How many complete months of history to export (3 by default), for the outcomes and the trend.

.PARAMETER HorizonDays
    How many days ahead of today to export (14 by default), for the calendar.

.PARAMETER BearerToken
    An OAuth access token (SecureString) instead of basic authentication.

.EXAMPLE
    .\scripts\Export-ChangeData.ps1 -Instance contoso -OutputFolder .\data

.EXAMPLE
    $t = Read-Host -AsSecureString 'OAuth token'; .\scripts\Export-ChangeData.ps1 -Instance contoso -BearerToken $t
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Instance,
    [string] $OutputFolder = '.\data',
    [int] $TrendMonths = 3,
    [int] $HorizonDays = 14,
    [int] $PageSize = 1000,
    [securestring] $BearerToken
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null
$base = if ($Instance -match '^https?://') { $Instance.TrimEnd('/') } else { "https://$Instance.service-now.com" }

$headers = @{ Accept = 'application/json' }
if ($BearerToken) {
    $headers.Authorization = 'Bearer ' + [Net.NetworkCredential]::new('', $BearerToken).Password
} else {
    $cred = Get-Credential -Message "ServiceNow user with read access for $base"
    $pair = '{0}:{1}' -f $cred.UserName, $cred.GetNetworkCredential().Password
    $headers.Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
    $pair = $null
}

function Write-Csv([object[]] $Rows, [string] $Name, [string[]] $Columns) {
    $path = Join-Path $OutputFolder $Name
    @($Rows) | Select-Object -Property $Columns | Export-Csv -Path $path -NoTypeInformation -Encoding utf8
    Write-Host ("{0,7} rows -> {1}" -f @($Rows).Count, $path)
}

function Get-Table([string] $Table, [string] $Query, [string[]] $Fields, [string] $DisplayValue = 'true') {
    # GET /api/now/table/<table>, page by page with sysparm_offset.
    $rows = [System.Collections.Generic.List[object]]::new()
    $offset = 0
    while ($true) {
        $qs = @(
            'sysparm_query=' + [uri]::EscapeDataString($Query)
            'sysparm_fields=' + [uri]::EscapeDataString($Fields -join ',')
            "sysparm_display_value=$DisplayValue"
            'sysparm_exclude_reference_link=true'
            "sysparm_limit=$PageSize"
            "sysparm_offset=$offset"
        ) -join '&'
        $r = Invoke-RestMethod -Method Get -Uri "$base/api/now/table/$($Table)?$qs" -Headers $headers
        $page = @($r.result)
        foreach ($x in $page) { $rows.Add($x) }
        Write-Verbose "$Table : $($rows.Count) records"
        if ($page.Count -lt $PageSize) { break }
        $offset += $PageSize
    }
    , $rows
}

$today = Get-Date
$since = (Get-Date -Year $today.Year -Month $today.Month -Day 1).AddMonths(-$TrendMonths).ToString('yyyy-MM-dd')
$until = $today.AddDays($HorizonDays + 1).ToString('yyyy-MM-dd')
$from = "javascript:gs.dateGenerate('$since','00:00:00')"
$to = "javascript:gs.dateGenerate('$until','00:00:00')"

# ---------------------------------------------------------------- change requests
$chgFields = 'number', 'short_description', 'type', 'state', 'risk', 'impact', 'cmdb_ci', 'business_service', 'assignment_group', 'assigned_to',
             'requested_by', 'opened_at', 'start_date', 'end_date', 'work_start', 'work_end', 'approval', 'cab_date', 'close_code', 'backout_plan',
             'test_plan', 'implementation_plan', 'justification', 'outside_maintenance_schedule', 'review_status', 'review_date'
$chg = Get-Table 'change_request' "start_date>=$from^start_date<$to^ORDERBYstart_date" $chgFields
Write-Csv $chg 'changes.csv' $chgFields

# ---------------------------------------------------------------- incidents
$incFields = 'number', 'short_description', 'priority', 'state', 'opened_at', 'resolved_at', 'cmdb_ci', 'business_service', 'assignment_group', 'caused_by'
$inc = Get-Table 'incident' "opened_at>=$from^ORDERBYopened_at" $incFields
Write-Csv $inc 'incidents.csv' $incFields

# ---------------------------------------------------------------- approvals of change requests
$aprFields = 'sysapproval', 'approver', 'state', 'sys_updated_on'
$apr = Get-Table 'sysapproval_approver' "sysapproval.sys_class_name=change_request^sys_updated_on>=$from^ORDERBYsys_updated_on" $aprFields
Write-Csv $apr 'approvals.csv' $aprFields

# ---------------------------------------------------------------- business services and their CIs
$svc = Get-Table 'cmdb_ci_service' 'operational_status=1^ORoperational_statusISEMPTY' @('sys_id', 'name', 'busines_criticality', 'owned_by', 'support_group')
$byId = @{}
foreach ($s in $svc) { $byId[$s.sys_id] = $s }
$rels = [System.Collections.Generic.List[object]]::new()
$ids = @($byId.Keys)
for ($i = 0; $i -lt $ids.Count; $i += 100) {
    $batch = $ids[$i..([Math]::Min($i + 99, $ids.Count - 1))] -join ','
    $q = "type.name=Depends on::Used by^parentIN$batch"
    foreach ($r in (Get-Table 'cmdb_rel_ci' $q @('parent', 'child.name', 'child.sys_class_name', 'child.sys_id') 'false')) { $rels.Add($r) }
}
$deps = @{}
$rows = foreach ($r in $rels) {
    $parent = $byId[$r.parent]
    if (-not $parent) { continue }
    if ($byId.ContainsKey($r.'child.sys_id')) {
        $deps[$parent.name] = @($deps[$parent.name]) + $r.'child.name' | Where-Object { $_ }
        continue
    }
    [pscustomobject] @{ ci = $r.'child.name'; ci_class = $r.'child.sys_class_name'; service = $parent.name }
}
$svcRows = foreach ($x in @($rows) + @($svc | ForEach-Object { [pscustomobject] @{ ci = ''; ci_class = ''; service = $_.name } })) {
    $s = $svc | Where-Object name -eq $x.service | Select-Object -First 1
    [pscustomobject] @{
        ci = $x.ci; ci_class = $x.ci_class; service = $x.service; service_tier = $s.busines_criticality
        service_owner = if ($s.support_group) { $s.support_group } else { $s.owned_by }
        service_depends_on = (@($deps[$x.service]) | Sort-Object -Unique) -join ';'
    }
}
Write-Csv $svcRows 'ci-services.csv' @('ci', 'ci_class', 'service', 'service_tier', 'service_owner', 'service_depends_on')

Write-Host "Done. Add freezes.csv (the freeze and blackout register), check settings.json, then run: python -m changecal review $OutputFolder"
