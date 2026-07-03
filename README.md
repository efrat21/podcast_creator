# Knigovishte Podcast Builder

A simple tool that automatically turns Bulgarian articles from [Knigovishte](https://www.knigovishte.bg/vijte) into bilingual (Bulgarian/English) audio podcast episodes delivered straight to your phone.

---

## Quick Setup

1. **Install dependencies:**
   Open your terminal/PowerShell and run:
   ```powershell
   pip install -r requirements.txt
   pip install -e .
   ```

2. **Configure your keys:**
   Create a file named `.env` in the project folder and add your translation and GitHub details:
   ```dotenv
   LANGBLY_API_KEY=your_key_here
   PODCAST_BASE_URL=https://<your-github-username>.github.io/<your-repository-name>/data/rss
   
   # Optional: Secure your Web UI with login credentials
   WEB_USERNAME=admin
   WEB_PASSWORD=your_secure_password
   ```

3. **Google Voices Setup:**
   Ensure your Google Cloud TTS credentials are set up in your system environment:
   ```powershell
   $env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\your-key.json"
   ```

4. **Enable GitHub Pages:**
   * Go to your repository on GitHub.com -> **Settings** -> **Pages**.
   * Under **Branch**, select `main` (or your active branch) and `/ (root)`. Click **Save**.

---

## How to Get New Episodes on Your Phone

Follow these 3 simple steps to create a new episode and sync it to your phone:

### Step 1: Generate the Audio
Run this command to automatically fetch the latest article, translate it, and generate the bilingual audio:
```powershell
python main.py run
```
*(If you want to make an episode for a specific article, add the URL: `python main.py run --url "https://www.knigovishte.bg/..."`)*

### Step 2: Update Your Podcast Feed
Rebuild the XML feed so the new episode is added to the list:
```powershell
python main.py local-rss-delivery --no-serve
```

### Step 3: Push to GitHub
Publish the files online so your phone can reach them:
```powershell
git add data/rss/
git commit -m "Add new podcast episode"
git push
```

---

## Listening on Your Phone

1. Open your favorite podcast app (such as **Podcast Addict** on Android or any RSS-friendly player).
2. Add a new podcast by URL / RSS feed.
3. Paste your public feed URL:
   ```text
   https://<your-github-username>.github.io/<your-repository-name>/data/rss/podcast.xml
   ```
4. Subscribe and enjoy! Whenever you push new episodes to GitHub in the future, your app will automatically update.

---

## Optional: Use the Web Interface
If you prefer a visual web interface over commands:
1. Run:
   ```powershell
   python main.py web
   ```
2. Open `http://127.0.0.1:8085` in your web browser. (If `WEB_USERNAME` and `WEB_PASSWORD` are set, log in with them).
3. Enter an article URL (or leave blank for the latest one) and click **Generate podcast artifacts**.
4. The Web UI will **automatically** run the RSS generator and push the updated feed to your GitHub repository in the background. Once it finishes, simply refresh the feed on your phone!
