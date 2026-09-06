[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ArgumentCompleter({
        param($commandName, $parameterName, $wordToComplete, $commandAst, $fakeBoundParameters)
        try {
            $cliDirectory = $PSScriptRoot
            $windowsPython = Join-Path $cliDirectory '.venv/Scripts/python.exe'
            $unixPython = Join-Path $cliDirectory '.venv/bin/python'
            $cliPython = if (Test-Path -LiteralPath $windowsPython) {
                $windowsPython
            } else {
                $unixPython
            }
            if (-not (Test-Path -LiteralPath $cliPython)) {
                return
            }
            $baseUrl = if ($fakeBoundParameters.ContainsKey('BaseUrl')) {
                [string] $fakeBoundParameters['BaseUrl']
            } elseif ($env:FUSION_HEADLESS_URL) {
                $env:FUSION_HEADLESS_URL
            } else {
                'http://127.0.0.1:5000'
            }
            $describe = @(
                (Join-Path $cliDirectory 'fusion_cli.py'),
                '--describe-powershell-verbs',
                '--base-url', $baseUrl
            )
            $descriptionJson = (& $cliPython @describe 2>$null) -join [Environment]::NewLine
            if ($LASTEXITCODE -ne 0) {
                return
            }
            foreach ($candidate in ($descriptionJson | ConvertFrom-Json)) {
                if ($candidate -like "$wordToComplete*") {
                    [System.Management.Automation.CompletionResult]::new(
                        [string] $candidate,
                        [string] $candidate,
                        [System.Management.Automation.CompletionResultType]::ParameterValue,
                        "FusionHeadless endpoint /$candidate"
                    )
                }
            }
        } catch {
            return
        }
    })]
    [string] $Verb,

    [string] $BaseUrl = $(if ($env:FUSION_HEADLESS_URL) { $env:FUSION_HEADLESS_URL } else { 'http://127.0.0.1:5000' }),
    [double] $Timeout,
    [switch] $Raw,
    [string] $Output,
    [string[]] $Query,
    [string] $Data
)

dynamicparam {
    $dictionary = [System.Management.Automation.RuntimeDefinedParameterDictionary]::new()
    # Verb completion happens before PowerShell binds the positional value.
    # Endpoint-specific switches can only be derived after a verb is present.
    if ([string]::IsNullOrWhiteSpace($Verb)) {
        return $dictionary
    }
    $script:CliDirectory = $PSScriptRoot
    $windowsPython = Join-Path $script:CliDirectory '.venv/Scripts/python.exe'
    $unixPython = Join-Path $script:CliDirectory '.venv/bin/python'
    $script:CliPython = if (Test-Path -LiteralPath $windowsPython) {
        $windowsPython
    } else {
        $unixPython
    }
    $script:DynamicParameters = @{}
    if (-not (Test-Path -LiteralPath $script:CliPython)) {
        throw "fusion_cli: CLI environment not found. Run: py -m venv `"$(Join-Path $script:CliDirectory '.venv')`"; & `"$script:CliPython`" -m pip install -r `"$(Join-Path $script:CliDirectory 'requirements.txt')`""
    }
    $describe = @(
        (Join-Path $script:CliDirectory 'fusion_cli.py'),
        '--describe-powershell', $Verb,
        '--base-url', $BaseUrl
    )
    $descriptionJson = (& $script:CliPython @describe 2>$null) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) {
        return $dictionary
    }

    foreach ($definition in ($descriptionJson | ConvertFrom-Json)) {
        $attributes = [System.Collections.ObjectModel.Collection[System.Attribute]]::new()
        $parameterAttribute = [System.Management.Automation.ParameterAttribute]::new()
        $parameterAttribute.HelpMessage = $definition.description
        $parameterAttribute.Mandatory = [bool] $definition.required
        $attributes.Add($parameterAttribute)
        if ($definition.choices.Count -gt 0) {
            $attributes.Add([System.Management.Automation.ValidateSetAttribute]::new([string[]] $definition.choices))
        }
        $type = switch ($definition.kind) {
            'boolean' { [switch] }
            'integer' { [int] }
            'number'  { [double] }
            'array'   { [string[]] }
            default   { [string] }
        }
        $runtimeParameter = [System.Management.Automation.RuntimeDefinedParameter]::new(
            [string] $definition.name,
            $type,
            $attributes
        )
        $dictionary.Add($definition.name, $runtimeParameter)
        $script:DynamicParameters[$definition.name] = $definition
    }
    return $dictionary
}

end {
    $arguments = @($Verb, '--base-url', $BaseUrl)
    foreach ($name in @('Raw')) {
        if ($PSBoundParameters.ContainsKey($name) -and $PSBoundParameters[$name]) {
            $arguments += '--' + ($name -creplace '([a-z0-9])([A-Z])', '$1-$2').ToLowerInvariant()
        }
    }
    foreach ($entry in @{
        Timeout = '--timeout'; Output = '--output'; Data = '--data'
    }.GetEnumerator()) {
        if ($PSBoundParameters.ContainsKey($entry.Key)) {
            $arguments += @($entry.Value, [string] $PSBoundParameters[$entry.Key])
        }
    }
    foreach ($expression in $Query) {
        $arguments += @('--query', $expression)
    }
    foreach ($name in $script:DynamicParameters.Keys) {
        if (-not $PSBoundParameters.ContainsKey($name)) {
            continue
        }
        $definition = $script:DynamicParameters[$name]
        $value = $PSBoundParameters[$name]
        if ($definition.kind -eq 'boolean') {
            if ($value) {
                $arguments += $definition.flag
            }
            elseif ($definition.falseFlag) {
                $arguments += $definition.falseFlag
            }
        }
        elseif ($definition.kind -eq 'array') {
            foreach ($item in $value) {
                $arguments += @($definition.flag, [string] $item)
            }
        }
        else {
            $arguments += @($definition.flag, [string] $value)
        }
    }
    & $script:CliPython (Join-Path $script:CliDirectory 'fusion_cli.py') @arguments
    exit $LASTEXITCODE
}
