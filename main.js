const { app, BrowserWindow, globalShortcut } = require("electron");
const { spawn } = require("child_process");

let flaskProcess;
let mainWindow;

app.whenReady().then(() => {

    // Start Flask
    flaskProcess = spawn("python", ["app.py"], {
        cwd: __dirname,
        shell: true
    });

    setTimeout(() => {

        mainWindow = new BrowserWindow({
            fullscreen: true,
            kiosk: true,
            frame: false,
            autoHideMenuBar: true,

            webPreferences: {
                contextIsolation: true,
                nodeIntegration: false
            }
        });

        mainWindow.loadURL("http://127.0.0.1:5000");

        // ONLY application exit shortcut
        globalShortcut.register("Ctrl+Shift+Q", () => {
            app.quit();
        });

    }, 2000);
});

app.on("will-quit", () => {

    globalShortcut.unregisterAll();

    if (flaskProcess) {
        flaskProcess.kill();
    }
});

app.on("window-all-closed", () => {
    app.quit();
});