; AstroSwarm 星群 安装包脚本（Inno Setup 6）
; 一站式安装：复制客户端 -> 立刻自动部署机器人运行环境（Python + NoneBot2）-> 写安装根指针。
; 客户装完就是可用状态，不会再遇到"打开程序又要装一次"的二次部署向导。
; 用法：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\AstroSwarm_setup.iss
; 产物：dist\AstroSwarm_Setup.exe
; 静默安装（同样会执行部署，可用 /DEPLOYROOT 指定部署目录）：
;   AstroSwarm_Setup.exe /SILENT /DEPLOYROOT="D:\AstroSwarm 星群\机器人"
; 不带 /DEPLOYROOT 时，机器人环境默认装到安装目录下的「机器人」子文件夹（跟着安装目录走）。

#define MyAppName "AstroSwarm 星群"
#define MyAppVersion "1.2.5"
#define MyAppExeName "AstroSwarm.exe"

[Setup]
AppId={{D3A8B1C2-9F4E-4B7A-8C5D-1E2F3A4B5C6D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=AstroSwarm
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=no
PrivilegesRequired=lowest
CloseApplications=yes
OutputDir=..\dist
OutputBaseFilename=AstroSwarm_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："
Name: "autostart"; Description: "开机自动启动（登录 Windows 后自动运行星群）"; GroupDescription: "附加任务："
Name: "autoservices"; Description: "启动程序时自动启动全部服务"; GroupDescription: "附加任务："; Check: NeedsDeploy

[Files]
Source: "..\dist\AstroSwarm.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\uninstall.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist_package\AstroSwarm_客户版\使用说明.docx"; DestDir: "{app}"; Flags: ignoreversion
; 只用于"查看用户协议"按钮，按需展开（dontcopy 不随安装复制）
Source: "..\src\qbotmanager\assets\agreements\user_eula.txt"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\卸载 {#MyAppName}"; Filename: "{app}\uninstall.exe"

[Registry]
; 与程序内「设置 → 开机自动启动」写的是同一个值名（HKCU\Software\Microsoft\Windows\CurrentVersion\Run\AstroSwarm），
; 安装时勾了这里就写，用户在程序里改也不会打架；卸载时自动删除（uninsdeletevalue）。
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AstroSwarm"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: autostart; Flags: uninsdeletevalue

[UninstallDelete]
; 机器人环境默认装在安装目录下的「机器人」子文件夹，卸载时一并删除。
; 用户在部署页改成别的磁盘时这个子目录根本不存在，删了也不会误伤。
Type: filesandordirs; Name: "{app}\机器人"

[Run]
; 关键一步：文件复制完立刻跑 `AstroSwarm.exe --cli deploy`，装好 Python 运行时 + NoneBot2 依赖并写安装根指针。
; StatusMsg 会让安装程序显示部署进度页（CreateOutputProgressPage 负责文案），客户不需要再点任何东西。
Filename: "{app}\{#MyAppExeName}"; Parameters: "{code:DeployParams}"; StatusMsg: "正在部署机器人运行环境（Python + NoneBot2），请保持网络畅通…"; Flags: runhidden waituntilterminated; Check: ShouldDeployNow
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 AstroSwarm"; Flags: nowait postinstall skipifsilent

[Code]
var
  DeployRootPage: TInputDirWizardPage;
  DeployConsentPage: TWizardPage;
  DeployNowCheck: TNewCheckBox;
  ConsentCheck: TNewCheckBox;
  EulaButton: TNewButton;
  DeployInfo: TNewStaticText;
  OutputPage: TOutputProgressWizardPage;
  LastAutoDeployRoot: String;  { 最近一次由安装目录推导出的部署根，用来判断用户有没有手动改过 }

function AppRobotRoot(): String;
begin
  { 整合布局：机器人环境默认落到安装目录下的「机器人」子文件夹 }
  Result := AddBackslash(ExpandConstant('{app}')) + '机器人';
end;

function PointerFile(): String;
begin
  Result := ExpandConstant('{userappdata}\QBotManager\settings.json');
end;

function RecentRootsFile(): String;
begin
  Result := ExpandConstant('{userappdata}\QBotManager\recent_roots.json');
end;

function DefaultDeployRoot(): String;
begin
  Result := ExpandConstant('{param:DeployRoot|}');
  if Result = '' then
    Result := AppRobotRoot();
end;

function NeedsDeploy(): Boolean;
begin
  { 安装根指针存在 = 之前已经部署过（老用户升级 / 重复安装），不重复部署，免得覆盖现有机器人环境。
    指针里存的是 JSON（路径带转义），安装脚本不解析它——卸载路径下由下面的
    CurUninstallStepChanged 负责在删掉整合目录时一并清掉指针，避免重装被误判成"已部署"。 }
  Result := not FileExists(PointerFile());
end;

function DeployRoot(): String;
begin
  if Assigned(DeployRootPage) and (DeployRootPage.Values[0] <> '') then
    Result := DeployRootPage.Values[0]
  else
    Result := DefaultDeployRoot();
end;

procedure SyncDeployRootWithAppDir();
var
  Cur, NewRoot: String;
begin
  if not Assigned(DeployRootPage) then Exit;
  NewRoot := AppRobotRoot();
  Cur := DeployRootPage.Values[0];
  { 只在「当前值还是自动推导出来的那个」时才跟随，用户自己填过路径就不动它 }
  if (Cur = '') or (CompareText(Cur, LastAutoDeployRoot) = 0) then
  begin
    DeployRootPage.Values[0] := NewRoot;
    LastAutoDeployRoot := NewRoot;
  end;
end;

function ShouldDeployNow(): Boolean;
begin
  Result := NeedsDeploy();
  if Result and (not WizardSilent) and Assigned(DeployNowCheck) then
    Result := DeployNowCheck.Checked;
end;

function DeployParams(Param: String): String;
begin
  Result := '--cli deploy --root "' + DeployRoot() + '"';
  if WizardIsTaskSelected('autoservices') then
    Result := Result + ' --auto-start-services';
end;

procedure ShowEula(Sender: TObject);
var
  ErrorCode: Integer;
  Source: String;
  Target: String;
begin
  Source := ExpandConstant('{tmp}\user_eula.txt');
  Target := ExpandConstant('{tmp}\AstroSwarm 用户协议与免责声明.txt');
  ExtractTemporaryFile('user_eula.txt');
  FileCopy(Source, Target, False);
  if not FileExists(Target) then
  begin
    MsgBox('协议文件未能展开，安装目录里的《使用说明.docx》有同样的说明。', mbInformation, MB_OK);
    Exit;
  end;
  if not ShellExec('open', Target, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    MsgBox('无法自动打开协议文件，请手动查看：' + Target, mbError, MB_OK);
end;

procedure InitializeWizard();
begin
  OutputPage := CreateOutputProgressPage('正在部署机器人运行环境',
    '正在下载 Python 运行时并安装 NoneBot2 依赖，通常需要 1-5 分钟，请保持网络畅通。');
  OutputPage.SetProgress(0, 0);

  if not NeedsDeploy() then
    Exit;

  DeployRootPage := CreateInputDirPage(wpSelectTasks,
    '选择机器人部署目录',
    'Python 运行时、NoneBot2 和机器人项目总共约 4 GB，默认装在安装目录下的「机器人」子文件夹里（跟着安装目录一起变）；想放别的磁盘可以在下面改。',
    '部署到：', False, '');
  DeployRootPage.Add('');
  { 这里不能算默认值：InitializeWizard 阶段 app 常量还没初始化，
    会报 attempt to expand the app constant before it was initialized。
    默认值留到离开「选择目标位置」页或本页真正显示时再填，见 SyncDeployRootWithAppDir。 }

  DeployConsentPage := CreateCustomPage(DeployRootPage.ID,
    '部署选项与用户协议', '安装程序会在文件复制完成后自动完成机器人环境部署，中途无需你做任何操作。');

  DeployInfo := TNewStaticText.Create(DeployConsentPage.Surface);
  DeployInfo.Parent := DeployConsentPage.Surface;
  DeployInfo.Left := 0;
  DeployInfo.Top := 0;
  DeployInfo.Width := DeployConsentPage.SurfaceWidth;
  DeployInfo.AutoSize := False;
  DeployInfo.Height := ScaleY(74);
  DeployInfo.Caption :=
    '安装程序会自动完成：' + #13#10 +
    '    1. 下载并解压 Python 3.12 运行时（无需自己装 Python）' + #13#10 +
    '    2. 安装 NoneBot2 及依赖（走国内镜像，约 1-5 分钟）' + #13#10 +
    '    3. 生成机器人项目骨架并写入安装根指针（下次启动直接进主界面）';

  DeployNowCheck := TNewCheckBox.Create(DeployConsentPage.Surface);
  DeployNowCheck.Parent := DeployConsentPage.Surface;
  DeployNowCheck.Left := 0;
  DeployNowCheck.Top := DeployInfo.Top + DeployInfo.Height + ScaleY(10);
  DeployNowCheck.Width := DeployConsentPage.SurfaceWidth;
  DeployNowCheck.Caption := '文件复制完成后立即部署机器人运行环境（推荐）';
  DeployNowCheck.Checked := True;

  ConsentCheck := TNewCheckBox.Create(DeployConsentPage.Surface);
  ConsentCheck.Parent := DeployConsentPage.Surface;
  ConsentCheck.Left := 0;
  ConsentCheck.Top := DeployNowCheck.Top + ScaleY(30);
  ConsentCheck.Width := DeployConsentPage.SurfaceWidth;
  ConsentCheck.Height := ScaleY(38);
  ConsentCheck.Caption := '我已阅读并同意《用户协议与免责声明》：QQ 机器人通过第三方 OneBot 协议接入，' +
    '第三方协议端由用户自行安装并承担账号风险，请自备小号。';

  EulaButton := TNewButton.Create(DeployConsentPage.Surface);
  EulaButton.Parent := DeployConsentPage.Surface;
  EulaButton.Left := 0;
  EulaButton.Top := ConsentCheck.Top + ConsentCheck.Height + ScaleY(10);
  EulaButton.Width := ScaleX(200);
  EulaButton.Caption := '查看《用户协议与免责声明》';
  EulaButton.OnClick := @ShowEula;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if not NeedsDeploy() then
  begin
    if Assigned(DeployRootPage) and (PageID = DeployRootPage.ID) then
      Result := True
    else if Assigned(DeployConsentPage) and (PageID = DeployConsentPage.ID) then
      Result := True;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { 静默安装不会走到这里；那种情况由 DeployRoot() 回退到 DefaultDeployRoot() 兜底 }
  if Assigned(DeployRootPage) and (CurPageID = DeployRootPage.ID) then
    SyncDeployRootWithAppDir();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  { 用户在「选择目标位置」页改了安装目录时，把还没被手动改过的部署目录跟着挪过去 }
  if CurPageID = wpSelectDir then
    SyncDeployRootWithAppDir();
  { 静默安装（/SILENT、/VERYSILENT）没有界面，勾选项无从点起；命令行即视为已同意 }
  if WizardSilent then
    Exit;
  if Assigned(DeployConsentPage) and (CurPageID = DeployConsentPage.ID) then
  begin
    if DeployNowCheck.Checked and (not ConsentCheck.Checked) then
    begin
      MsgBox('请先阅读并同意《用户协议与免责声明》后再继续安装。', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssDone) and ShouldDeployNow() then
  begin
    if not FileExists(DeployRoot() + '\settings.json') then
      MsgBox('机器人运行环境这次没有部署成功（常见原因是网络中断）。' + #13#10 +
        '程序本身已经装好，首次打开时会自动引导你重新部署。', mbInformation, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    { 整合布局：机器人环境就在安装目录下的「机器人」子文件夹里（[UninstallDelete] 会删掉它）。
      此时安装根指针必须一起清掉，否则下次重装会被 NeedsDeploy 当成"已经部署过"而跳过部署，
      装完打开就只剩首次运行向导。用户把部署目录改到别的磁盘时这个子目录不存在，指针保持不动，
      重装依旧能沿用他原来的机器人环境。 }
    if DirExists(AppRobotRoot()) then
    begin
      DeleteFile(PointerFile());
      DeleteFile(RecentRootsFile());
      { 两个启动记录都清掉后，空目录一并收走，重装完全等同全新安装 }
      RemoveDir(ExpandConstant('{userappdata}\QBotManager'));
    end;
  end;
end;
