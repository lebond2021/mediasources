param([string]$Target = "gh:github.com:lebond2021")
$ErrorActionPreference = 'Stop'
Add-Type -Namespace Win -Name Cred -MemberDefinition @'
[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
public struct CREDENTIAL {
    public uint Flags;
    public uint Type;
    public string TargetName;
    public string Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
    public uint CredentialBlobSize;
    public IntPtr CredentialBlob;
    public uint Persist;
    public uint AttributeCount;
    public IntPtr Attributes;
    public string TargetAlias;
    public string UserName;
}
[DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
public static extern bool CredReadW(string target, uint type, uint flags, out IntPtr credential);
[DllImport("advapi32.dll", SetLastError=true)]
public static extern void CredFree(IntPtr cred);
'@

$ptr = [IntPtr]::Zero
if (-not [Win.Cred]::CredReadW($Target, 1, 0, [ref]$ptr)) {
    $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    Write-Output "READ-FAIL target=$Target err=$err"
    exit 1
}
try {
    $c = [Runtime.InteropServices.Marshal]::PtrToStructure($ptr, [type][Win.Cred+CREDENTIAL])
    $bytes = New-Object byte[] $c.CredentialBlobSize
    [Runtime.InteropServices.Marshal]::Copy($c.CredentialBlob, $bytes, 0, $c.CredentialBlobSize)
    $blobU = [Text.Encoding]::Unicode.GetString($bytes).TrimEnd([char]0)
    $blobA = [Text.Encoding]::UTF8.GetString($bytes).TrimEnd([char]0)
    $blob = if ($blobU -match '^[A-Za-z0-9_\-\.]+$') { $blobU }
            elseif ($blobA -match '^[A-Za-z0-9_\-\.]+$') { $blobA }
            else { $blobU }
    Write-Output "user=$($c.UserName) len=$($blob.Length) prefix=$($blob.Substring(0,[Math]::Min(4,$blob.Length)))"
    if ($env:GH_TOKEN_OUT) {
        [IO.File]::WriteAllText($env:GH_TOKEN_OUT, $blob, [Text.UTF8Encoding]::new($false))
        Write-Output "写入 $env:GH_TOKEN_OUT"
    }
} finally {
    [Win.Cred]::CredFree($ptr)
}
