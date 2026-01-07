import os
import requests
import json
from dotenv import load_dotenv

# 加载环境配置
load_dotenv(override=True)


class NewsFetcher:
    def __init__(self):
        # 1. 自动去除 API Key 前后的空格
        raw_key = os.getenv("CRYPTOPANIC_API_KEY", "")
        self.api_key = raw_key.strip()

        # [修改] 去掉 URL 末尾的斜杠，防止拼接出错
        # 如果你是免费 Key，请将 v2 改回 v1: https://cryptopanic.com/api/v1/posts
        self.base_url = "https://cryptopanic.com/api/developer/v2/posts/"

        # 2. 代理配置
        self.proxies = None
        proxy_port = os.getenv("PROXY_PORT")

        if proxy_port:
            port = proxy_port.strip()
            proxy_url = f"http://127.0.0.1:{port}"
            self.proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
            print(f"🌍 [新闻模块] 代理已配置: {proxy_url}")
        else:
            print("⚠️ [新闻模块] 未配置 PROXY_PORT，尝试直连")

    def test_connection(self):
        """测试代理连通性"""
        try:
            print("📡 测试 Google 连通性...")
            resp = requests.get("https://www.google.com", proxies=self.proxies, timeout=5)
            if resp.status_code == 200:
                print("✅ 代理网络通畅！")
                return True
            else:
                print(f"⚠️ 状态码: {resp.status_code}")
                return False
        except Exception as e:
            print(f"❌ 代理连接失败: {e}")
            return False

    def get_latest_news(self, symbol="BTC", limit=5):
        """
        策略：优先抓取重大新闻，如果没有，则抓取普通新闻。
        """
        if not self.api_key:
            return "No news API key configured."

        currency = symbol.split('/')[0]

        # === 第一步：尝试获取“重要”新闻 ===
        # print("🔍 正在搜索重大新闻...")
        news_text = self._fetch_internal(currency, filter_mode="important", limit=limit)

        # === 第二步：如果没抓到，降级获取“所有”新闻 ===
        if not news_text:
            print("⚠️ 暂无重大新闻，降级获取最新资讯...")
            news_text = self._fetch_internal(currency, filter_mode=None, limit=limit)

        # 如果还是没有
        if not news_text:
            return "No news found currently."

        return news_text

    def _fetch_internal(self, currency, filter_mode, limit):
        """内部请求逻辑"""
        params = {
            "auth_token": self.api_key,
            "currencies": currency,
            "kind": "news",
            "public": "true"
        }
        # 只有当指定了 filter 时才传参
        if filter_mode:
            params["filter"] = filter_mode

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            response = requests.get(
                self.base_url,
                params=params,
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )

            if response.status_code != 200:
                # 只在出错时打印详细 URL，方便调试
                if response.status_code in [403, 404]:
                    print(f"❌ 请求失败 ({response.status_code}) | 可能原因: 接口版本不对(V1/V2) 或 Key权限不足")
                    # print(f"🔗 Debug URL: {response.url}")
                return None

            data = response.json()
            results = data.get('results', [])

            if not results:
                return None

            news_summary = []
            for item in results[:limit]:
                title = item.get('title', 'Unknown')
                # 时间格式化: 2024-01-01T12:00:00Z -> 2024-01-01 12:00
                published_at = item.get('published_at', '').replace('T', ' ')[:16]
                source = item.get('source', {}).get('title', 'Web')

                # 图标区分：重要新闻用 🔥，普通新闻用 📢
                icon = "🔥" if filter_mode == "important" else "📢"

                news_summary.append(f"- {icon} [{published_at}] ({source}) {title}")

            return "\n".join(news_summary)

        except Exception as e:
            print(f"⚠️ 抓取异常: {e}")
            return None


if __name__ == "__main__":
    fetcher = NewsFetcher()
    if fetcher.test_connection():
        print("\n📰 测试智能抓取 (BTC):")
        print(fetcher.get_latest_news("BTC/USDT"))
    else:
        print("❌ 代理未通，无法测试")