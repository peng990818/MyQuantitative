import os

import requests
import time
from utils.config_loader import ConfigLoader
from utils.proxy_manager import ProxyManager


class NewsFetcher:
    def __init__(self):
        self.cfg = ConfigLoader()
        self.api_key = self.cfg.get("news_keys.cryptopanic")
        self.base_url = "https://cryptopanic.com/api/developer/v2/posts/"

        # 从 ProxyManager 获取标准代理字典
        self.proxies = ProxyManager(self.cfg).get_proxies()

    def get_latest_news(self, symbol="BTC", limit=5):
        if not self.api_key:
            return "No news API key configured."

        currency = symbol.split('/')[0]
        # 1. 尝试重要新闻
        news = self._fetch(currency, "important", limit)
        if news: return news

        # 2. 强制冷却 (防 429)
        time.sleep(1)

        # 3. 尝试普通新闻
        return self._fetch(currency, None, limit)

    def _fetch(self, currency, filter_mode, limit):
        params = {
            "auth_token": self.api_key,
            "currencies": currency,
            "kind": "news",
            "public": "true"
        }
        if filter_mode: params["filter"] = filter_mode

        headers = {"User-Agent": "QuantBot/v2.0"}

        # 重试机制
        for attempt in range(3):
            try:
                resp = requests.get(
                    self.base_url,
                    params=params,
                    headers=headers,
                    proxies=self.proxies,  # 🔥 自动注入代理
                    timeout=10
                )

                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get('results', [])
                    if not results: return None

                    summary = []
                    for item in results[:limit]:
                        title = item.get('title')
                        date = item.get('published_at', '')[:16].replace('T', ' ')
                        icon = "🔥" if filter_mode == "important" else "📢"
                        summary.append(f"- {icon} [{date}] {title}")
                    return "\n".join(summary)

                elif resp.status_code == 429:
                    wait = 2 * (attempt + 1)
                    print(f"⏳ [News] 触发限流，等待 {wait}s...")
                    time.sleep(wait)
                    continue

            except Exception as e:
                print(f"⚠️ News Fetch Error: {e}")
                return None
        return None

if __name__ == "__main__":
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    print("📰 正在测试 NewsFetcher...")
    try:
        fetcher = NewsFetcher()
        print("⏳ 正在抓取 BTC 新闻...")

        # 抓取 3 条
        news_text = fetcher.get_latest_news("BTC", limit=3)

        if news_text and "No news" not in news_text:
            print("✅ 抓取成功:\n" + "-" * 30)
            print(news_text)
            print("-" * 30)
        else:
            print(f"⚠️ 未抓取到内容 (原因: {news_text})")

    except Exception as e:
        print(f"❌ 测试失败: {e}")