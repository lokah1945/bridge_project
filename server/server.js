
require('dotenv').config();
const express = require('express');
const { chromium } = require('playwright-extra');
const stealth = require('puppeteer-extra-plugin-stealth')();
const path = require('path');
const fs = require('fs');
const readline = require('readline');

chromium.use(stealth);

const app = express();
const PORT = process.env.PORT || 9877;
const BASE_SESSION_DIR = path.join(__dirname, 'browser_sessions');
const PROFILES_FILE = path.join(__dirname, 'profiles.json');

if (!fs.existsSync(BASE_SESSION_DIR)) fs.mkdirSync(BASE_SESSION_DIR);

const sessionStore = {
    "arena": { "cookies": [], "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "headers": { "Accept-Language": "en-US,en;q=0.9" } },
    "qwen": { "cookies": [], "user_agent": "...", "headers": {} }
};

let browserContext;

function getProfiles() {
    if (!fs.existsSync(PROFILES_FILE)) return [];
    return JSON.parse(fs.readFileSync(PROFILES_FILE, 'utf8'));
}

function saveProfiles(profiles) {
    fs.writeFileSync(PROFILES_FILE, JSON.stringify(profiles, null, 2));
}

async function startServerWithProfile(profileName) {
    const profileDir = path.join(BASE_SESSION_DIR, profileName);
    console.log(`\n[Server] Launching Profile: ${profileName}...`);
    
    try {
        browserContext = await chromium.launchPersistentContext(profileDir, { 
            headless: process.env.BROWSER_HEADLESS === 'true',
            args: ['--remote-debugging-port=9222', '--start-maximized', '--disable-blink-features=AutomationControlled'],
            viewport: null
        });
        await browserContext.addInitScript(() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        });
        console.log(`[Server] Profile ${profileName} is now active.`);
    } catch (e) {
        console.error("[Server] Error starting profile:", e);
    }

    app.listen(PORT, '0.0.0.0', () => {
        console.log(`🚀 Bridge-Server running on port ${PORT}`);
        console.log(`🔑 Login URL: http://localhost:${PORT}/open?url=https://arena.ai/text/direct`);
    });
}

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

function mainMenu() {
    const profiles = getProfiles();
    console.log("\n=== BRIDGE-SERVER CONTROL PANEL ===");
    console.log("1. Start Server");
    console.log("2. Add New Profile");
    console.log("3. Delete Saved Profile");
    console.log("4. Exit");
    console.log("====================================");

    rl.question("Choose option: ", async (choice) => {
        if (choice === '1') {
            if (profiles.length === 0) {
                console.log("No profiles found. Please add a profile first.");
                mainMenu();
            } else if (profiles.length === 1) {
                await startServerWithProfile(profiles[0]);
            } else {
                console.log("\nAvailable Profiles:");
                profiles.forEach((p, i) => console.log(`${i + 1}. ${p}`));
                rl.question("Select profile number: ", async (num) => {
                    const idx = parseInt(num) - 1;
                    if (idx >= 0 && idx < profiles.length) {
                        await startServerWithProfile(profiles[idx]);
                    } else {
                        console.log("Invalid selection.");
                        mainMenu();
                    }
                });
            }
        } else if (choice === '2') {
            rl.question("Enter new profile name: ", (name) => {
                if (!name) return mainMenu();
                const profiles = getProfiles();
                if (profiles.includes(name)) {
                    console.log("Profile already exists.");
                } else {
                    profiles.push(name);
                    saveProfiles(profiles);
                    console.log(`Profile '${name}' added successfully.`);
                }
                mainMenu();
            });
        } else if (choice === '3') {
            const profiles = getProfiles();
            console.log("\nProfiles to delete:");
            profiles.forEach((p, i) => console.log(`${i + 1}. ${p}`));
            rl.question("Select profile number to delete: ", (num) => {
                const idx = parseInt(num) - 1;
                if (idx >= 0 && idx < profiles.length) {
                    const name = profiles[idx];
                    const dir = path.join(BASE_SESSION_DIR, name);
                    fs.rmSync(dir, { recursive: true, force: true });
                    profiles.splice(idx, 1);
                    saveProfiles(profiles);
                    console.log(`Profile '${name}' deleted.`);
                }
                mainMenu();
            });
        } else if (choice === '4') {
            process.exit(0);
        } else {
            mainMenu();
        }
    });
}

// API Endpoints
app.get('/open', async (req, res) => {
    const url = req.query.url;
    if (!url) return res.status(400).send("Missing url parameter");
    try {
        const page = await browserContext.newPage();
        await page.goto(url);
        res.send(`Navigated to ${url}`);
    } catch (e) { res.status(500).send(e.message); }
});

app.get('/get-session/:provider', async (req, res) => {
    const provider = req.params.provider.toLowerCase();
    if (!sessionStore[provider]) return res.status(404).json({ error: "Not found" });
    sessionStore[provider].cookies = await browserContext.cookies();
    res.json(sessionStore[provider]);
});

app.get('/health', (req, res) => res.json({ status: "online" }));

mainMenu();
