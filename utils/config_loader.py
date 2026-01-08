import yaml
import os
from utils.logger import logger  # 👈 引入新日志模块


class ConfigLoader:
    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_path, 'config', 'config.yaml')
        secrets_path = os.path.join(base_path, 'config', 'secrets.yaml')

        if not os.path.exists(config_path):
            logger.error(f"❌ 严重错误: 配置文件丢失 -> {config_path}")
            raise FileNotFoundError("config.yaml missing")

        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        if os.path.exists(secrets_path):
            with open(secrets_path, 'r', encoding='utf-8') as f:
                secrets = yaml.safe_load(f)
                self._merge_dicts(self._config, secrets)
                logger.info("✅ 密钥配置 (secrets.yaml) 已加载")
        else:
            # 🔥 [修改] 如果是为了测试，这里可以只打印 debug 或 info，不打印 warning 吓人
            logger.warning("⚠️ 密钥文件 (secrets.yaml) 未找到，API 功能将受限")

    def _merge_dicts(self, dict1, dict2):
        """递归合并字典"""
        for key, value in dict2.items():
            if key in dict1 and isinstance(dict1[key], dict) and isinstance(value, dict):
                self._merge_dicts(dict1[key], value)
            else:
                dict1[key] = value

    def get(self, key=None, default=None):
        """
        获取配置，支持点号访问，并支持默认值。
        示例: config.get('ai.model_name', 'deepseek-chat')
        """
        if key is None:
            return self._config

        try:
            keys = key.split('.')
            val = self._config
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k)
                else:
                    return default

                if val is None:
                    return default
            return val
        except Exception:
            return default


# ... (上面的代码保持不变)

if __name__ == "__main__":
    # 🔥 路径魔法：让当前脚本能找到根目录的 utils
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    print("🛠️ 正在测试 ConfigLoader...")
    try:
        cfg = ConfigLoader()
        print(f"✅ 项目名称: {cfg.get('project_name')}")
        print(f"✅ 运行模式: {cfg.get('run_mode')}")

        # 测试读取密钥 (只会显示前几位)
        key = cfg.get("exchange.okx.api_key")
        print(f"✅ OKX Key: {key[:4]}******" if key else "❌ OKX Key 未配置")

        # 测试读取深层参数
        print(f"✅ 资金模式: {cfg.get('money_management.mode')}")
    except Exception as e:
        print(f"❌ 测试失败: {e}")