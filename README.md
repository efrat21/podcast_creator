# Knigovishte Podcast Builder

## 1. Introduction
The **Knigovishte Podcast Builder** is a tool that automatically converts Bulgarian articles from [Knigovishte](https://www.knigovishte.bg/vijte) into bilingual (Bulgarian/English) audio podcast episodes delivered straight to your phone.

> [!NOTE]
> * **If you only want to listen to existing episodes:** You do not need to install or configure anything. Just copy the RSS feed URL in **[Section 2](#2-listening-to-existing-episodes)** and add it to your favorite podcast application.
> * **If you want to create new episodes or change the app:** Follow the **[Quick Setup](#quick-setup)** below to clone, install, and configure the project.

### Quick Setup
1. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   pip install -e .
   ```
2. **Configure your keys:**
   Create a `.env` file in the project folder:
   ```dotenv
   LANGBLY_API_KEY=your_key_here
   PODCAST_BASE_URL=https://<your-github-username>.github.io/<your-repository-name>/data/rss

   # Optional: Secure Web UI credentials
   WEB_USERNAME=admin
   WEB_PASSWORD=your_secure_password
   ```
3. **Google Voices Setup:**
   Ensure Google Cloud TTS credentials are set in your environment:
   ```powershell
   $env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\your-key.json"
   ```
4. **Enable GitHub Pages:**
   In your GitHub repository settings, go to **Pages**, set the build source branch to `main` (or your active branch) and directory `/ (root)`, then click **Save**.

---

## 2. Listening to Existing Episodes
You can subscribe to and listen to all generated episodes on any RSS-friendly podcast player (such as **Podcast Addict** on Android or **Apple Podcasts**):

1. Copy your public feed URL:
   ```text
   https://<your-github-username>.github.io/<your-repository-name>/data/rss/podcast.xml
   ```
2. Open your podcast application.
3. Select **Add Podcast by URL** (or RSS Feed) and paste the URL.
4. Subscribe to get all current and future episodes delivered automatically.

---

## 3. Creating a New Episode
You can generate new episodes and update the podcast feed using any of the following methods:

### Method A: Web Interface (Recommended)
1. Run the local server:
   ```powershell
   python main.py web
   ```
2. Open `http://127.0.0.1:8085` in your browser.
3. Paste an article URL (or leave blank to process the latest one) and click **Generate Podcast Episode**. The system will automatically build the audio, update the RSS feed, and push it to GitHub.

### Method B: Command Line
1. Run the generator pipeline:
   ```powershell
   python main.py run --url "https://www.knigovishte.bg/vijte/..."
   ```
   *(Or leave out `--url` to select the latest article automatically).*
2. Rebuild the local feed:
   ```powershell
   python main.py local-rss-delivery --no-serve
   ```
3. Push to GitHub:
   ```powershell
   git add data/rss/
   git commit -m "Add new podcast episode"
   git push
   ```

### Method C: Automated Daily Check
The system runs a daily scheduled task (`KnigovishtePodcastDaily`) at **14:00** (2:00 PM) to check for new articles, generate the episode, rebuild the RSS feed, and publish it to GitHub completely automatically.
