import re

class DomainPicker:
    """基于字典与正则加权匹配的领域分类器"""
    
    def __init__(self):
        # 为系统关心的各个领域预定义核心关键词表 (支持多语言)
        self.domain_keywords = {
            "technology": [
                # EN & ZH
                "AI", "大模型", "Transformer", "LLM", "tech", "software", "apple", "google", 
                "microsoft", "芯片", "算法", "网络", "计算机", "科技", "智能", "cyber", "digital",
                # JA
                "テクノロジー", "技術", "ソフトウェア", "アプリ", "コンピュータ", "サイバー",
                # DE
                "Technologie", "KI", "Algorithmus", "Netzwerk", "Computer",
                # FR
                "technologie", "intelligence artificielle", "logiciel", "algorithme", "ordinateur"
            ],
            "politics": [
                # EN & ZH
                "government", "election", "policy", "minister", "president", "政府", "选举", 
                "政策", "部长", "总统", "议会", "外交", "democrat", "republican", "parliament",
                # JA
                "政治", "選挙", "政策", "首相", "大統領", "外交", "議会",
                # DE
                "Politik", "Regierung", "Wahl", "Partei", "Minister", "Präsident", "Parlament", "Diplomatie",
                # FR
                "politique", "gouvernement", "élection", "ministre", "président", "parlement", "diplomatie"
            ],
            "finance": [
                # EN & ZH
                "market", "economy", "stock", "bank", "inflation", "市场", "经济", "股票", 
                "银行", "通胀", "央行", "投资", "finance", "business", "rate", "invest",
                # JA
                "経済", "市場", "株式", "銀行", "インフレ", "投資", "金融", "ビジネス",
                # DE
                "Wirtschaft", "Markt", "Aktie", "Bank", "Inflation", "Investition", "Finanzen", "Unternehmen",
                # FR
                "économie", "marché", "bourse", "banque", "investissement", "entreprise"
            ],
            "science": [
                # EN & ZH
                "research", "study", "scientist", "physics", "space", "研究", "科学", "物理", 
                "太空", "发现", "基因", "climate", "nature", "evolution",
                # JA
                "科学", "研究", "物理", "宇宙", "発見", "遺伝子", "気候", "自然",
                # DE
                "Wissenschaft", "Forschung", "Physik", "Weltraum", "Entdeckung", "Genetik", "Klima", "Natur",
                # FR
                "science", "recherche", "physique", "espace", "découverte", "génétique", "climat", "nature"
            ],
            "culture": [
                # EN & ZH
                "art", "movie", "music", "history", "museum", "艺术", "电影", "音乐", "历史", 
                "文化", "博物馆", "literature", "heritage", "festival",
                # JA
                "文化", "芸術", "映画", "音楽", "歴史", "博物館", "伝統", "文学",
                # DE
                "Kultur", "Kunst", "Film", "Musik", "Geschichte", "Museum", "Literatur", "Tradition",
                # FR
                "culture", "art", "cinéma", "musique", "histoire", "musée", "littérature", "tradition"
            ],
            "health": [
                # EN & ZH
                "disease", "hospital", "patient", "cancer", "treatment", "疾病", "医院", 
                "患者", "癌症", "治疗", "医生", "medical", "virus", "vaccine", "health",
                # JA
                "医療", "健康", "病院", "患者", "がん", "治療", "ウイルス", "ワクチン", "病気",
                # DE
                "Gesundheit", "Medizin", "Krankenhaus", "Patient", "Krebs", "Behandlung", "Virus", "Krankheit",
                # FR
                "santé", "médecine", "hôpital", "patient", "cancer", "traitement", "virus", "maladie"
            ]
        }
        
        # 预编译正则以提升匹配速度，忽略大小写
        self.compiled_keywords = {}
        for domain, keywords in self.domain_keywords.items():
            # 使用 \b 来匹配英文单词边界，中文则直接匹配
            # 为了简单兼顾中英文，这里直接进行子串匹配
            pattern = re.compile("|".join(re.escape(kw) for kw in keywords), re.IGNORECASE)
            self.compiled_keywords[domain] = pattern
            
    def pick_domain(self, title: str, summary: str, content: str = "") -> str:
        """
        根据标题和摘要计算得分最高归属。
        如果摘要为空，截取正文前段作为摘要。
        """
        scores = {d: 0 for d in self.domain_keywords}
        
        # 兜底：如果没摘要，拿正文前 500 个字符代替
        text_to_scan = summary if summary.strip() else content[:500]
        
        for domain, pattern in self.compiled_keywords.items():
            if title:
                matches = len(pattern.findall(title))
                scores[domain] += matches * 2  # 标题权重：2分
            if text_to_scan:
                matches = len(pattern.findall(text_to_scan))
                scores[domain] += matches * 1  # 摘要/正文权重：1分
                
        best_domain = max(scores, key=scores.get)
        
        # 如果所有得分均为 0，归入未分类
        if scores[best_domain] == 0:
            return "unknown"
            
        return best_domain
