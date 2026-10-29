; Instalador de GESTOR (Inno Setup 6). Lo compila GitHub Actions:
;   ISCC.exe /DVersion=0.6.0 instalador\gestor.iss
; Lleva dentro todo el programa, así que instala sin conexión a internet.
; Al abrirlo muestra un menú: instalar o actualizar, reparar, preparar un paquete sin conexión,
; detener o reiniciar los servicios, respaldar la base de datos o salir.

#ifndef Version
  #define Version "0.0.0"
#endif
#define AppGuid "A7D3E5B2-4C91-4F0B-8E6A-2D5C9B1F7E43"

[Setup]
AppId={{{#AppGuid}}
AppName=GESTOR
AppVersion={#Version}
AppVerName=GESTOR {#Version}
AppPublisher=Alfonso
VersionInfoVersion={#Version}
VersionInfoDescription=Instalador de GESTOR
DefaultDirName={localappdata}\Programs\GESTOR
DefaultGroupName=GESTOR
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputDir=..\salida
OutputBaseFilename=GESTOR-Instalador-{#Version}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\GESTOR.exe
UninstallDisplayName=GESTOR
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"

[InstallDelete]
; Reinstalar o actualizar deja el programa limpio (tus datos están en %APPDATA%\GESTOR y no se tocan).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\GESTOR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Una copia del propio instalador, para abrir las herramientas desde el menú Inicio.
Source: "{srcexe}"; DestDir: "{app}\instalador"; DestName: "GESTOR-Instalador.exe"; Flags: external ignoreversion; Check: NoEsLaCopiaInstalada

[Icons]
Name: "{autoprograms}\GESTOR"; Filename: "{app}\GESTOR.exe"
Name: "{autoprograms}\GESTOR - Herramientas (reparar, detener, reiniciar, respaldar)"; Filename: "{app}\instalador\GESTOR-Instalador.exe"
Name: "{autodesktop}\GESTOR"; Filename: "{app}\GESTOR.exe"; Tasks: escritorio

[Run]
Filename: "{app}\GESTOR.exe"; Parameters: "--reiniciar"; StatusMsg: "Activando los servicios de GESTOR..."; Flags: runhidden waituntilterminated
Filename: "{app}\GESTOR.exe"; Description: "Abrir GESTOR"; Flags: postinstall nowait skipifsilent
; Actualización automática desde el panel: instala en silencio y vuelve a abrir GESTOR.
Filename: "{app}\GESTOR.exe"; Flags: nowait; Check: ReabrirTrasActualizar

[UninstallRun]
Filename: "{app}\GESTOR.exe"; Parameters: "--desinstalar"; Flags: runhidden waituntilterminated; RunOnceId: "QuitarServicios"

[Code]
var
  Opciones: TInputOptionWizardPage;
  RutaInstalada, VersionInstalada: String;
  Instalado, SalirSinPreguntar: Boolean;

const
  OP_INSTALAR = 0;
  OP_REPARAR = 1;
  OP_PAQUETE = 2;
  OP_DETENER = 3;
  OP_REINICIAR = 4;
  OP_RESPALDAR = 5;
  OP_SALIR = 6;

function NoEsLaCopiaInstalada: Boolean;
begin
  // Si se repara desde la copia del menú Inicio, no se puede sobrescribir a sí misma.
  Result := CompareText(ExpandConstant('{srcexe}'), ExpandConstant('{app}\instalador\GESTOR-Instalador.exe')) <> 0;
end;

function ReabrirTrasActualizar: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:reabrir|0}') = '1');
end;

function ClaveDesinstalar: String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#AppGuid}' + '}_is1';
end;

function Exe: String;
begin
  Result := AddBackslash(RutaInstalada) + 'GESTOR.exe';
end;

function Ejecutar(Parametros: String): Boolean;
var
  Codigo: Integer;
begin
  Result := Exec(Exe, Parametros, RutaInstalada, SW_HIDE, ewWaitUntilTerminated, Codigo) and (Codigo = 0);
end;

procedure InitializeWizard;
var
  Estado: String;
begin
  Instalado := RegQueryStringValue(HKCU, ClaveDesinstalar, 'InstallLocation', RutaInstalada)
               and FileExists(AddBackslash(RutaInstalada) + 'GESTOR.exe');
  if Instalado then
  begin
    RegQueryStringValue(HKCU, ClaveDesinstalar, 'DisplayVersion', VersionInstalada);
    Estado := 'GESTOR ' + VersionInstalada + ' está instalado en ' + RutaInstalada + '.';
  end else
    Estado := 'GESTOR no está instalado en este equipo. Este instalador lleva todo dentro: no necesita internet.';

  Opciones := CreateInputOptionPage(wpWelcome, 'Instalador de GESTOR {#Version}', '¿Qué quieres hacer?', Estado, True, False);
  if Instalado then
    Opciones.Add('Actualizar a la versión {#Version}  (se respalda la base de datos antes)')
  else
    Opciones.Add('Instalar GESTOR {#Version}');
  Opciones.Add('Reinstalar para reparar errores  (tus servicios y datos se conservan)');
  Opciones.Add('Preparar un paquete para instalar sin conexión  (en otra PC o una USB)');
  Opciones.Add('Detener los servicios');
  Opciones.Add('Reiniciar los servicios');
  Opciones.Add('Respaldar la base de datos');
  Opciones.Add('Salir');
  Opciones.SelectedValueIndex := OP_INSTALAR;
  if not Instalado then
  begin
    Opciones.CheckListBox.ItemEnabled[OP_REPARAR] := False;
    Opciones.CheckListBox.ItemEnabled[OP_DETENER] := False;
    Opciones.CheckListBox.ItemEnabled[OP_REINICIAR] := False;
    Opciones.CheckListBox.ItemEnabled[OP_RESPALDAR] := False;
  end;
end;

procedure PrepararPaquete;
var
  Carpeta: String;
begin
  Carpeta := ExpandConstant('{userdocs}');
  if not BrowseForFolder('Elige dónde guardar el paquete (por ejemplo, tu USB):', Carpeta, True) then
    exit;
  Carpeta := AddBackslash(Carpeta) + 'GESTOR {#Version} sin conexion';
  ForceDirectories(Carpeta);
  if FileCopy(ExpandConstant('{srcexe}'), AddBackslash(Carpeta) + 'GESTOR-Instalador-{#Version}.exe', False) then
  begin
    SaveStringToFile(AddBackslash(Carpeta) + 'LEEME.txt',
      'GESTOR {#Version} - paquete para instalar sin conexión' + #13#10 + #13#10 +
      'Abre GESTOR-Instalador-{#Version}.exe en el otro equipo y elige "Instalar".' + #13#10 +
      'No necesita internet: el instalador lleva todo el programa dentro.' + #13#10 +
      'Si Windows avisa de que protegió el equipo, pulsa "Más información" y "Ejecutar de todas formas".' + #13#10, False);
    MsgBox('Paquete listo en:' + #13#10 + Carpeta + #13#10 + #13#10 +
           'Copia esa carpeta al otro equipo (o déjala en tu USB) y abre el instalador desde ahí.', mbInformation, MB_OK);
  end else
    MsgBox('No se pudo copiar el instalador a esa carpeta.', mbError, MB_OK);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID <> Opciones.ID then
    exit;
  case Opciones.SelectedValueIndex of
    OP_PAQUETE:
      begin
        Result := False;
        PrepararPaquete;
      end;
    OP_DETENER:
      begin
        Result := False;
        if Ejecutar('--detener') then
          MsgBox('Servicios detenidos. GESTOR no ordenará nada hasta que los reinicies (aquí o desde el panel).', mbInformation, MB_OK)
        else
          MsgBox('No se pudieron detener los servicios. Mira %APPDATA%\GESTOR\mantenimiento.log.', mbError, MB_OK);
      end;
    OP_REINICIAR:
      begin
        Result := False;
        if Ejecutar('--reiniciar') then
          MsgBox('Servicios reiniciados: la tarea programada y el icono vuelven a funcionar.', mbInformation, MB_OK)
        else
          MsgBox('No se pudieron reiniciar los servicios. Mira %APPDATA%\GESTOR\mantenimiento.log.', mbError, MB_OK);
      end;
    OP_RESPALDAR:
      begin
        Result := False;
        if Ejecutar('--respaldar-base') then
          MsgBox('Base de datos respaldada en Documentos\GESTOR\Respaldos de la base.', mbInformation, MB_OK)
        else
          MsgBox('No se pudo respaldar la base de datos. Mira %APPDATA%\GESTOR\mantenimiento.log.', mbError, MB_OK);
      end;
    OP_SALIR:
      begin
        Result := False;
        SalirSinPreguntar := True;
        WizardForm.Close;
      end;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if SalirSinPreguntar then
    Confirm := False;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if Instalado then
  begin
    WizardForm.StatusLabel.Caption := 'Respaldando la base de datos y cerrando GESTOR...';
    Ejecutar('--respaldar-base');
    Ejecutar('--cerrar-procesos');
  end;
end;
