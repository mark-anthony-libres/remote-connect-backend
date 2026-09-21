@echo off
if exist .venv (
    echo Virtual environment already exists. Activating...
    call .venv\Scripts\activate.bat
) else (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Error: Failed to create virtual environment. Make sure Python is installed.
        exit /b 1
    )
    call .venv\Scripts\activate.bat
    echo Installing requirements...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Error: Failed to install requirements.
        exit /b 1
    )
    echo Installing taskipy for npm-like script running...
    pip install taskipy
    if errorlevel 1 (
        echo Warning: Failed to install taskipy. You can still use setup_venv.bat directly.
    )
    echo Virtual environment created and activated successfully!
    echo You can now use: python -m run setup
)
