# Knigovishte Podcast Builder

## 1. Introduction

**Knigovishte Podcast Builder** helps people improve their **Bulgarian listening comprehension** in a fun and engaging way. It automatically turns articles from [Knigovishte kids news](https://www.knigovishte.bg/vijte) into bilingual (Bulgarian/English) podcast episodes by using **AI to translate the text and generate natural-sounding speech**. The finished episodes can be listened to in any podcast app, making it easy to practice Bulgarian while enjoying interesting stories and articles.

This project was created using **agents vibe coding**, with AI-assisted development powered by **GitHub Copilot** and **Bradygaster/Squad**. It demonstrates how modern AI development tools can be used to quickly build a practical application that solves a real language-learning problem.

> [!NOTE]
>
> * **If you only want to listen to existing episodes:** You do not need to install or configure anything. Simply copy the RSS feed URL **https://efrat21.github.io/podcast_creator/data/rss/podcast.xml** and add it to your favorite podcast app. see **[Listening to Episodes](#2-listening-to-episodes)** section for detailed explanations.
> * **If you want to create new episodes or modify the application:** Follow the **[Quick Setup](#quick-setup)** below to clone, install, and configure the project.

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
   GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\your-key.json"
   PODCAST_BASE_URL=https://<your-github-username>.github.io/<your-repository-name>/data/rss
   ```
3. **Enable GitHub Pages:**
   In your GitHub repository settings, go to **Pages**, set the build source branch to `main` (or your active branch) and directory `/ (root)`, then click **Save**.

---

## 2. Listening to Episodes
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

### Method C: Automated Daily Daemon
You can run a continuous background daemon that automatically checks for new articles once a day:
1. Run the background daemon:
   ```powershell
   python main.py daily-daemon
   ```
   *(This starts a background loop that wakes up once every 24 hours to check for new articles, translate them, generate audio, rebuild the RSS feed, and push everything to GitHub. You can customize the check interval using the `--interval` flag in seconds, e.g., `--interval 3600` to check every hour).*
2. **Note:** There is also a scheduled daily task (`KnigovishtePodcastDaily`) registered on your system to run the daily check automatically every day at **14:00** (2:00 PM).
