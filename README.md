# downloader

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> ⚠️ **免责声明 / Disclaimer**  
> 本工具仅供学生下载本人已注册课程的课件，方便离线学习。  
> This tool is for students to download course materials they are enrolled in, for offline study purposes only.  
> 请遵守所在机构 IT 使用政策。  
> Please comply with your institution's IT Acceptable Use Policy.

---

## 中文版

Moodle 课件资源自动下载工具。Rich 终端界面，支持 Chrome / Edge / Firefox。

### ✨ 特性

| 特性 | 说明 |
|------|------|
| 🖥️ **Rich 终端界面** | 进度条、仪表盘、文件类型图标 |
| ⚡ **24 线程并行** | 默认 24 线程同时下载 |
| 🌐 **多浏览器支持** | Chrome / Edge / Firefox 自动检测 |
| 📋 **课程列表** | 列出已注册课程，一键选择下载 |
| 🔑 **自动登录** | Selenium 浏览器登录 + Okta SSO，Cookie 复用 |
| 🧠 **深度扫描** | 自动钻进子页面挖掘嵌套课件链接 |
| 📁 **智能命名** | 自动抓取课程名，保存到对应目录 |
| 🛡️ **防闪退** | 任何错误都有暂停画面，信息不丢失 |

### 📦 安装

```bash
pip install -r requirements.txt
```

另需安装 WebDriver（至少一个）：[Chrome](https://chromedriver.chromium.org/) / [Edge](https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/) / [Firefox](https://github.com/mozilla/geckodriver/releases)

### 🚀 使用

```bash
python main.py                     # 登录 → 列出课程 → 选择下载
python main.py 98120               # 直接下载指定课程
python main.py --browser chrome    # 指定浏览器
python main.py --help
```

首次运行自动打开浏览器完成登录。Cookie 持久化，下次无需重复登录。

### ⚙️ 配置

编辑 `config.toml`：

```toml
[download]
max_workers = 24

[browser]
type = ""

[filters]
file_keywords = ["lecture"]
file_extensions = [".pdf", ".ppt", ".pptx"]
```

### 🧪 测试

```bash
pip install pytest
python -m pytest tests/ -q
```

### 📄 许可

MIT License — 见 [LICENSE](LICENSE)。

---

## English Version

A Moodle course materials downloader. Rich terminal UI with support for Chrome / Edge / Firefox.

### ✨ Features

| Feature | Description |
|--------|-------------|
| 🖥️ **Rich Terminal UI** | Progress bars, dashboard, file type icons |
| ⚡ **24-thread Parallel** | Downloads and scans with 24 threads |
| 🌐 **Multi-browser** | Auto-detect Chrome / Edge / Firefox |
| 📋 **Course List** | Lists enrolled courses for one-click download |
| 🔑 **Auto Login** | Selenium browser login + SSO, cookie persistence |
| 🧠 **Deep Scan** | Crawls sub-pages for nested resources |
| 📁 **Smart Naming** | Auto-detects course name, saves to matching folder |
| 🛡️ **Crash Protection** | Catches errors gracefully, never closes silently |

### 📦 Installation

```bash
pip install -r requirements.txt
```

Also install a WebDriver (at least one): [Chrome](https://chromedriver.chromium.org/) / [Edge](https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/) / [Firefox](https://github.com/mozilla/geckodriver/releases)

### 🚀 Usage

```bash
python main.py                     # Login → list courses → pick & download
python main.py 98120               # Download a specific course by ID
python main.py --browser chrome    # Specify browser
python main.py --help
```

On first run, the browser will open automatically for login. Cookies are saved for future use.

### ⚙️ Configuration

Edit `config.toml`:

```toml
[download]
max_workers = 24

[browser]
type = ""

[filters]
file_keywords = ["lecture"]
file_extensions = [".pdf", ".ppt", ".pptx"]
```

### 🧪 Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

### 📄 License

MIT License — see [LICENSE](LICENSE).

---

> 🌐 **受限于作者时间，English Version of downloader 将在不久的将来上线。**  
> Due to the author's limited availability, a dedicated English version of the downloader is in progress and will be released soon.
