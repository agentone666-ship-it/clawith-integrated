"""Initial guest provisioning sources; never interpolate model input or credentials."""

CONSOLE_LAUNCHER = r'''
"""Administrator-only provisioning helper; launch in the existing guest console."""
import ctypes as c
from ctypes import wintypes as w
import sys
class STARTUPINFO(c.Structure):
 _fields_=[('cb',w.DWORD),('lpReserved',w.LPWSTR),('lpDesktop',w.LPWSTR),('lpTitle',w.LPWSTR),('dwX',w.DWORD),('dwY',w.DWORD),('dwXSize',w.DWORD),('dwYSize',w.DWORD),('dwXCountChars',w.DWORD),('dwYCountChars',w.DWORD),('dwFillAttribute',w.DWORD),('dwFlags',w.DWORD),('wShowWindow',w.WORD),('cbReserved2',w.WORD),('lpReserved2',c.c_void_p),('hStdInput',w.HANDLE),('hStdOutput',w.HANDLE),('hStdError',w.HANDLE)]
class PROCESSINFO(c.Structure):
 _fields_=[('hProcess',w.HANDLE),('hThread',w.HANDLE),('dwProcessId',w.DWORD),('dwThreadId',w.DWORD)]
k=c.WinDLL('kernel32',use_last_error=True);t=c.WinDLL('wtsapi32',use_last_error=True);a=c.WinDLL('advapi32',use_last_error=True);u=c.WinDLL('userenv',use_last_error=True)
k.CloseHandle.argtypes=[w.HANDLE]
u.DestroyEnvironmentBlock.argtypes=[c.c_void_p]
k.WTSGetActiveConsoleSessionId.restype=w.DWORD
t.WTSQueryUserToken.argtypes=[w.ULONG,c.POINTER(w.HANDLE)]
u.CreateEnvironmentBlock.argtypes=[c.POINTER(c.c_void_p),w.HANDLE,w.BOOL]
a.CreateProcessAsUserW.argtypes=[w.HANDLE,w.LPCWSTR,w.LPWSTR,c.c_void_p,c.c_void_p,w.BOOL,w.DWORD,c.c_void_p,w.LPCWSTR,c.POINTER(STARTUPINFO),c.POINTER(PROCESSINFO)]
token=w.HANDLE();env=c.c_void_p();pi=PROCESSINFO();si=STARTUPINFO();si.cb=c.sizeof(si);si.lpDesktop='winsta0\\default'
if not t.WTSQueryUserToken(k.WTSGetActiveConsoleSessionId(),c.byref(token)):raise c.WinError(c.get_last_error())
if not u.CreateEnvironmentBlock(c.byref(env),token,False):raise c.WinError(c.get_last_error())
cmd=c.create_unicode_buffer(sys.argv[1])
if not a.CreateProcessAsUserW(token,None,cmd,None,None,False,0x400|0x8000000,env,'C:\\Clawith',c.byref(si),c.byref(pi)):raise c.WinError(c.get_last_error())
print('console_process_id',pi.dwProcessId)
k.CloseHandle(pi.hThread);k.CloseHandle(pi.hProcess);k.CloseHandle(token);u.DestroyEnvironmentBlock(env)
'''

FIRST_LOGON = r"""
$ErrorActionPreference='Stop'
$result=@{ok=$false;user=[Security.Principal.WindowsIdentity]::GetCurrent().Name;is_system=[Security.Principal.WindowsIdentity]::GetCurrent().IsSystem}
try {
 if ($result.is_system) {throw 'Desktop registration requires the interactive user'}
 # Register framework and its consumers atomically: an unreferenced standalone
 # framework can be scavenged immediately after a successful registration.
 $framework='C:\Windows\SystemApps\Microsoft.UI.Xaml.CBS_8wekyb3d8bbwe\AppxManifest.xml'
 foreach($name in @('ShellExperienceHost_cw5n1h2txyewy','Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy')) {
  Add-AppxPackage -Register -Path "C:\Windows\SystemApps\$name\AppxManifest.xml" -DependencyPath $framework -DisableDevelopmentMode -ErrorAction Stop
 }
 foreach($name in @('MicrosoftWindows.Client.CBS_cw5n1h2txyewy','MicrosoftWindows.Client.Core_cw5n1h2txyewy')) {
  $file="C:\Windows\SystemApps\$name\AppxManifest.xml"
  if (Test-Path $file) {Add-AppxPackage -Register -Path $file -DisableDevelopmentMode -ErrorAction Stop}
 }
 $desktop=[Environment]::GetFolderPath('Desktop')
 $shell=New-Object -ComObject WScript.Shell
 $browser='C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
 if(Test-Path $browser) {$link=$shell.CreateShortcut("$desktop\Microsoft Edge.lnk");$link.TargetPath=$browser;$link.Save()}
 $link=$shell.CreateShortcut("$desktop\This PC.lnk");$link.TargetPath='C:\Windows\explorer.exe';$link.Arguments='shell:MyComputerFolder';$link.Save()
 $result.ok=$true
} catch {$result.error=$_.Exception.Message}
$result | ConvertTo-Json | Set-Content C:\Clawith\private\first-logon-ready.json
"""

AUTOLOGON_SECRET = r"""

using System;
using System.Runtime.InteropServices;
public static class ClawithAutoLogon {
 [StructLayout(LayoutKind.Sequential)] struct US {public ushort Length;public ushort MaximumLength;public IntPtr Buffer;}
 [StructLayout(LayoutKind.Sequential)] struct OA {public uint Length;public IntPtr RootDirectory;public IntPtr ObjectName;public uint Attributes;public IntPtr SecurityDescriptor;public IntPtr SecurityQualityOfService;}
 [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr system,ref OA attributes,uint access,out IntPtr handle);
 [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(IntPtr handle,ref US key,ref US value);
 [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr handle);
 [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint status);
 static US Make(string text) {return new US{Length=(ushort)(text.Length*2),MaximumLength=(ushort)(text.Length*2+2),Buffer=Marshal.StringToHGlobalUni(text)};}
 public static void Set(string password) {
  OA attrs=new OA();attrs.Length=(uint)Marshal.SizeOf(typeof(OA));IntPtr handle;uint status=LsaOpenPolicy(IntPtr.Zero,ref attrs,0x20,out handle);
  if(status!=0) throw new System.ComponentModel.Win32Exception((int)LsaNtStatusToWinError(status));
  US key=Make("DefaultPassword"),value=Make(password);
  try {status=LsaStorePrivateData(handle,ref key,ref value);if(status!=0) throw new System.ComponentModel.Win32Exception((int)LsaNtStatusToWinError(status));}
  finally {Marshal.ZeroFreeGlobalAllocUnicode(value.Buffer);Marshal.FreeHGlobal(key.Buffer);LsaClose(handle);}
 }
}
"""

CONTROLLER_STARTUP = r"""$ErrorActionPreference='Stop'
$p=Start-Process -FilePath 'C:\Clawith\Python\python.exe' -ArgumentList @('-X','utf8','C:\Clawith\bridge.py') -WorkingDirectory 'C:\Clawith' -WindowStyle Hidden -RedirectStandardOutput 'C:\Clawith\logs\bridge.stdout.log' -RedirectStandardError 'C:\Clawith\logs\bridge.stderr.log' -Wait -PassThru
exit $p.ExitCode
"""
