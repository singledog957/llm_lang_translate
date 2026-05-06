import os
from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.tmt.v20180321 import tmt_client, models

load_dotenv()

class Translator:
    def __init__(self):
        # 尝试从环境变量获取
        secret_id = os.environ.get("SecretId")
        secret_key = os.environ.get("SecretKey")
        
        # 如果没有获取到，尝试直接读取 .env 文件解析 (支持 key:value 格式)
        if not secret_id or not secret_key:
            env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if ':' in line:
                            key, val = line.split(':', 1)
                            if key.strip() == 'SecretId':
                                secret_id = val.strip()
                            elif key.strip() == 'SecretKey':
                                secret_key = val.strip()

        if not secret_id or not secret_key:
            raise ValueError("Tencent Cloud SecretId and SecretKey must be set in .env")
        
        # 实例化一个认证对象，入参需要传入腾讯云账户 SecretId 和 SecretKey
        self.cred = credential.Credential(secret_id, secret_key)
        
        # 实例化一个http选项，可选的，没有特殊需求可以跳过
        httpProfile = HttpProfile()
        httpProfile.endpoint = "tmt.tencentcloudapi.com"

        # 实例化一个client选项，可选的，没有特殊需求可以跳过
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        
        # 实例化要请求产品的client对象,clientProfile是可选的
        # 地域参数可选填，这里使用 ap-guangzhou
        self.client = tmt_client.TmtClient(self.cred, "ap-guangzhou", clientProfile)

    def translate_text(self, source_text: str, source_lang: str, target_lang: str, project_id: int = 0) -> str:
        """
        使用腾讯云机器翻译API翻译文本。
        
        Args:
            source_text (str): 待翻译的文本。
            source_lang (str): 源语言（如 'en', 'zh', 'ja' 等）。
            target_lang (str): 目标语言（如 'zh', 'en', 'ko' 等）。
            project_id (int): 项目ID，默认为0。
            
        Returns:
            str: 翻译后的文本。
        """
        try:
            # 实例化一个请求对象,每个接口都会对应一个request对象
            req = models.TextTranslateRequest()
            params = {
                "SourceText": source_text,
                "Source": source_lang,
                "Target": target_lang,
                "ProjectId": project_id
            }
            req.from_json_string(import_json_dumps(params))

            # 返回的resp是一个TextTranslateResponse的实例，与请求对象对应
            resp = self.client.TextTranslate(req)
            # 输出json格式的字符串回包
            return resp.TargetText
            
        except TencentCloudSDKException as err:
            print(f"Translation Error: {err}")
            return ""

def import_json_dumps(params):
    import json
    return json.dumps(params)
