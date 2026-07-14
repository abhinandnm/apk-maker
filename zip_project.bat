@echo off
setlocal

set "ZIP_NAME=kuttans-app-builder-deploy.zip"

echo ====================================================
echo Creating lightweight deployment bundle...
echo ====================================================

:: Remove existing zip if it exists
if exist "%ZIP_NAME%" del "%ZIP_NAME%"

:: Create temporary staging folder
if exist "deploy_temp" rd /s /q "deploy_temp"
mkdir "deploy_temp"
mkdir "deploy_temp\routes"
mkdir "deploy_temp\builders"
mkdir "deploy_temp\services"
mkdir "deploy_temp\templates"
mkdir "deploy_temp\static"

:: Copy files
copy "app.py" "deploy_temp\"
copy "requirements.txt" "deploy_temp\"
copy "setup_ec2.sh" "deploy_temp\"
copy "README.md" "deploy_temp\"
copy ".gitignore" "deploy_temp\"

xcopy "routes" "deploy_temp\routes" /E /I /Q /Y
xcopy "builders" "deploy_temp\builders" /E /I /Q /Y
xcopy "services" "deploy_temp\services" /E /I /Q /Y
xcopy "templates" "deploy_temp\templates" /E /I /Q /Y
xcopy "static" "deploy_temp\static" /E /I /Q /Y

:: Create empty folders
mkdir "deploy_temp\uploads"
mkdir "deploy_temp\apks"
mkdir "deploy_temp\logs"

:: Zip the staging folder using PowerShell
powershell -Command "Compress-Archive -Path 'deploy_temp\*' -DestinationPath '%ZIP_NAME%' -Force"

:: Clean up staging folder
rd /s /q "deploy_temp"

echo ====================================================
echo SUCCESS! Created: %ZIP_NAME%
echo Size:
powershell -Command "(Get-Item '%ZIP_NAME%').Length / 1KB" | findstr /R "^[0-9]"
echo.
echo You only need to upload this single ZIP file to EC2!
echo ====================================================
pause
