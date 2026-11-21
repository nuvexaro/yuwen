; yuwen（余温）Windows 安装脚本 —— Inno Setup 6
;
; 构建（在仓库根目录执行，输出目录用相对路径传入）：
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /O"..\..\_release" packaging\installer.iss
;
; 约定：
;   - 脚本内所有路径都是相对路径（相对本文件所在目录 packaging\），不含任何本机绝对路径。
;   - 安装包内容来自 PyInstaller 的 onedir 产物：..\dist_pkg\dist\ex-ai-pilot\
;   - 简体中文语言文件来自 Inno Setup 官方 Unofficial 翻译：
;     Files/Languages/Unofficial/ChineseSimplified.isl（is-6_7_3 分支），随仓库一起分发。
;   - AppId 一经发布不可更改，后续版本升级必须沿用同一个 GUID。

#define AppName "yuwen"
#define AppNameCN "余温"
#define AppVersion "0.2.0"
#define AppPublisher "nuvexaro"
#define AppURL "https://github.com/nuvexaro/yuwen"
#define AppExeName "ex-ai-pilot.exe"

#ifndef SourceDir
  #define SourceDir "..\dist_pkg\dist\ex-ai-pilot"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist_pkg\installer"
#endif

[Setup]
; 固定 AppId（GUID 手工生成一次，此后所有版本复用；不要改）
AppId={{8C4A2F1E-9D3B-4E7A-B6C2-1F0D5A7E3B94}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup

; 装在当前用户下，不需要管理员权限
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; 输出
OutputDir={#OutputDir}
OutputBaseFilename=yuwen-v{#AppVersion}-setup-windows-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; 卸载入口：出现在「设置 → 应用」里
UninstallDisplayName={#AppName}（{#AppNameCN}）
UninstallDisplayIcon={app}\{#AppExeName}

; 只允许 64 位 Windows
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
// 用户数据目录：与程序分离，卸载时不做任何删除
function UserDataDir(): String;
begin
  Result := ExpandConstant('{%USERPROFILE}\.ex_ai');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Msg: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 静默卸载（/VERYSILENT）时不弹窗，避免自动化/脚本被阻塞
    if UninstallSilent then
      Exit;
    if ActiveLanguage = 'chinesesimplified' then
      Msg := 'yuwen 已卸载。' + #13#10#13#10 +
             '你的聊天记录、人格文件和会话记录都保留在：' + #13#10 +
             '  ' + UserDataDir() + #13#10#13#10 +
             '本安装程序没有删除它们。如需彻底清除，请手动删除上面这个文件夹' + #13#10 +
             '（删除后不可恢复）。'
    else
      Msg := 'yuwen has been uninstalled.' + #13#10#13#10 +
             'Your chat logs, persona files and sessions are kept in:' + #13#10 +
             '  ' + UserDataDir() + #13#10#13#10 +
             'The uninstaller did not delete them. To remove everything, delete' + #13#10 +
             'that folder manually (this cannot be undone).';
    MsgBox(Msg, mbInformation, MB_OK);
  end;
end;
