require('dotenv').config();
const express = require('express');
const { chromium } = require('playwright-extra');
const stealth = require('puppeteer-extra-plugin-stealth')();
const path = require('path');
const fs = require('fs');
const readline = require('readline');

chromium.use(stealth);

const app = express();
app.use(express.json());
const PORT = process.env.PORT || 9877;
const BASE_SESSION_DIR = path.join(__dirname, 'browser_sessions');
const PROFILES_FILE = path.join(__dirname, 'profiles.json');

if (!fs.existsSync(BASE_SESSION_DIR)) fs.mkdirSync(BASE_SESSION_DIR);

const sessionStore = {
    "arena": { "cookies": [], "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "headers": { "Accept-Language": "en-US,en;q=0.9" } },
    "qwen": { "cookies": [], "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "headers": {} },
    "deepseek": { "cookies": [], "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "headers": {} }
};

let browserContext;

async function applyCDPStealth(page) {
    try {
        const client = await page.context().newCDPSession(page);
        await client.send('Page.addScriptToEvaluateOnNewDocument', {
            source: `
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1] });
                Object.defineProperty(window, 'chrome', { get: () => ({ runtime: {} }) });
            `
        });
        await client.send('Network.setExtraHTTPHeaders', {
            headers: {
                'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A brand";v="//"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
            }
        });
    } catch (e) { console.error("[CDP] Stealth Error:", e); }
}

async function startServerWithProfile(profileName) {
    const profileDir = path.join(BASE_SESSION_DIR, profileName);
    try {
        browserContext = await chromium.launchPersistentContext(profileDir, { 
            headless: process.env.BROWSER_HEADLESS === 'true',
            args: [
                '--remote-debugging-port=9222',
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-web-security'
            ],
            viewport: null
        });
        const page = await browserContext.newPage();
        await applyCDPStealth(page);
        console.log(`[Server] Profile ${profileName} active.`);
    } catch (e) { console.error("[Server] Error:", e); }

    app.listen(PORT, '0.0.0.0', () => {
        console.log(`🚀 Session-Server running on port ${PORT}`);
    });
}

app.get('/open', async (req, res) => {
    const url = req.query.url;
    if (!url) return res.status(400).send("Missing url");
    try {
        const page = await browserContext.newPage();
        await applyCDPStealth(page);
        await page.goto(url, { waitUntil: 'networkidle' });
        res.send(`Navigated to ${url}. Please login in the browser.`);
    } catch (e) { res.status(500).send(e.message); }
});

app.get('/get-session/:provider', async (req, res) => {
    const provider = req.params.provider.toLowerCase();
    if (!sessionStore[provider]) return res.status(404).json({ error: "Provider not configured" });
    
    try {
        const cookies = await browserContext.cookies();
        sessionStore[provider].cookies = cookies;
        res.json(sessionStore[provider]);
    } catch (e) {
        res.status(500).json({ error: "Failed to fetch cookies: " + e.message });
    }
});

app.get('/health', (req, res) => res.json({ status: "online" }));

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
function getProfiles() { return fs.existsSync(PROFILES_FILE) ? JSON.parse(fs.readFileSync(PROFILES_FILE, 'utf8')) : []; }
function saveProfiles(p) { fs.writeFileSync(PROFILES_FILE, JSON.stringify(p, null, 2)); }

function mainMenu() {
    const profiles = getProfiles();
    console.log("\n=== SESSION-BRIDGE CONTROL PANEL ===");
    console.log("1. Start Server");
    console.log("2. Add New Profile");
    console.log("3. Delete Saved Profile");
    console.log("4. Exit");
    rl.question("Choose: ", async (choice) => {
        if (choice === '1') {
            if (profiles.length === 0) { console.log("No profiles."); mainMenu(); }
            else {
                profiles.forEach((p, i) => console.log(`${i + 1}. ${p}`));
                rl.question("Select: ", async (num) => {
                    const idx = parseInt(num) - 1;
                    if (idx >= 0 && idx < profiles.length) await startServerWithProfile(profiles[idx]);
                    else mainMenu();
                });
            }
        } else if (choice === '2') {
            rl.question("Name: ", (name) => {
                const p = getProfiles(); p.push(name); saveProfiles(p);
                mainMenu();
            });
        } else if (choice === '3') {
            const p = getProfiles();
            p.forEach((name, i) => console.log(`${i+1}. ${name}`));
            rl.question("Index: ", (num) => {
                const idx = parseInt(num)-1;
                if (idx >= 0 && idx < p.length) {
                    fs.rmSync(path.join(BASE_SESSION_DIR, p[idx]), { recursive: true, force: true });
                    p.splice(idx, 1); saveProfiles(p);
                }
                mainMenu();
            });
        } else if (choice === '4') process.exit(0);
        else mainMenu();
    });
}

mainMenu();
