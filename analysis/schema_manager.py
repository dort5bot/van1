# schema_manage.py schema_manager
# analysis_schema.yaml yükleyici yapısına bire bir uyumlu bir şema tanımlar ve yükleyiciyi içerir
"""
Sorumluluk: YAML şemasını yükleme, validasyon, filtreleme işlemleri
Neden ayrı?: Data access layer pattern - veri erişim mantığını soyutlama
Avantaj: Router ve core modüllerinden bağımsız çalışabilir

| Özellik                      | Açıklama                                             |
| ---------------------------- | ---------------------------------------------------- |
| 🧩 Tam `pydantic` uyumu      | `analysis_schema.yaml` ile birebir eşleşir            |
| 🎛️ `priority` filtresi      | `*`, `**`, `***` seviyelerinde filtreleme fonksiyonu |
| 🚀 Kullanıcı seviyesi seçimi | "basic", "pro", "expert" gibi user level uyarlaması  |
| 🔍 Modül & metrik arama      | Komut, dosya ya da isimle modül bulma                |
| 🧪 Gelişmiş test örneği      | Modül & metrikleri filtreleyerek yazdırır            |
| 🧠 Genişletmeye hazır yapı   | API, CLI, UI ya da test framework için uygun         |

Analizleri özelleştirebilirsin
GET /regime → default (tümü)
GET /regime?priority=* → sadece hızlı/temel
GET /regime?priority=*** → yalnızca ileri düzey

⚙️ GEREKSİNİM

Her analiz modül dosyasında (örneğin tremo.py) şu fonksiyon tanımlı olmalı:

# örnek: analysis/tremo.py
async def run(symbol: str, priority: Optional[str] = None) -> dict:
    return {"score": 0.74, "symbol": symbol, "priority": priority}


Bu işlevin symbol ve priority parametresini alması gerekiyor.

"""
# schema_manage.py
# Geliştirilmiş versiyon: priority filtresi + kullanıcı seviyesi desteği + modül/metrik arama

from typing import List, Optional, Literal, Union
from pydantic import BaseModel
import yaml
import importlib.util
import os

# --- Şema Tanımları ---

PriorityLevel = Literal["*", "**", "***"]

class Metric(BaseModel):
    name: str
    priority: PriorityLevel

# analysis_schema.yaml için modül
class Module(BaseModel):
    name: str
    file: str
    command: str
    api_type: str
    endpoints: List[str]
    methods: List[Literal["GET", "POST", "PUT", "DELETE", "WebSocket"]]

    classical_metrics: Optional[List[Union[str, Metric]]] = []
    professional_metrics: Optional[List[Metric]] = []
    composite_metrics: Optional[List[str]] = []
    development_notes: Optional[str] = None
    objective: Optional[str] = None
    output_type: Optional[str] = None

class AnalysisSchema(BaseModel):
    modules: List[Module]


# --- Yükleyici Fonksiyon ---

def load_analysis_schema(yaml_path: str = "analysis/analysis_schema.yaml") -> AnalysisSchema:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return AnalysisSchema(**data)


# --- Filtreleme & Yardımcı Fonksiyonlar ---

def filter_modules_by_priority(schema: AnalysisSchema, priority: PriorityLevel) -> List[Module]:
    """
    Verilen priority seviyesine göre modülleri filtreler (sadece ilgili metrik içerenler döner)
    """
    filtered = []
    for module in schema.modules:
        if any(m.priority == priority for m in module.professional_metrics or []):
            filtered.append(module)
    return filtered

def get_metrics_by_priority(module: Module, priority: PriorityLevel) -> List[Metric]:
    """
    Bir modül içindeki belirli öncelikteki metrikleri döner
    """
    return [m for m in (module.professional_metrics or []) if m.priority == priority]

def get_module_by_command(schema: AnalysisSchema, command: str) -> Optional[Module]:
    return next((m for m in schema.modules if m.command == command), None)

def get_module_by_file(schema: AnalysisSchema, file: str) -> Optional[Module]:
    return next((m for m in schema.modules if m.file == file), None)

def get_module_by_name(schema: AnalysisSchema, name: str) -> Optional[Module]:
    return next((m for m in schema.modules if m.name == name), None)




# her analiz modül dosyasının içinden run() fonksiyonunu otomatik yükler.
def load_module_run_function(module_file: str):
    """
    Verilen module file (örneğin tremo.py) için run() fonksiyonunu dinamik olarak yükler.
    """
    module_path = os.path.join("analysis", module_file)
    module_name = module_file.replace(".py", "")

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if not spec or not spec.loader:
        raise ImportError(f"Modül yüklenemedi: {module_file}")
    
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "run"):
        raise AttributeError(f"{module_file} içinde 'run()' fonksiyonu bulunamadı.")

    return mod.run


# --- Kullanıcı Seviyesi Filtresi ---

USER_LEVEL_PRIORITY = {
    "basic": "*",
    "pro": "**",
    "expert": "***"
}

def get_modules_for_user_level(schema: AnalysisSchema, level: str) -> List[Module]:
    """
    Kullanıcı seviyesine göre modülleri döner
    """
    priority = USER_LEVEL_PRIORITY.get(level.lower())
    if priority:
        return filter_modules_by_priority(schema, priority)
    return []


# --- Test Örneği ---

if __name__ == "__main__":
    schema = load_analysis_schema()

    print("📊 Tüm modüller:")
    for module in schema.modules:
        print(f" - [{module.command}] {module.name} (file: {module.file})")

    print("\n🎯 Önceliği *** olan metrikleri içeren modüller:")
    high_priority_modules = filter_modules_by_priority(schema, "***")
    for mod in high_priority_modules:
        metrics = get_metrics_by_priority(mod, "***")
        print(f"\n🔍 {mod.name} ({mod.command})")
        for m in metrics:
            print(f"   - {m.name} ({m.priority})")

    print("\n👤 Pro seviye kullanıcıya uygun modüller:")
    pro_mods = get_modules_for_user_level(schema, "pro")
    for mod in pro_mods:
        print(f" - {mod.name} ({mod.command})")




"""
🔧 Bundan Sonra Ne Yapabilirim?

Şimdi bu yapıyı kullanarak şunları kolayca ekleyebiliriz:
| Amaç                       | Ne Yapabilirim?                                             |
| -------------------------- | ----------------------------------------------------------- |
| 📡 API router              | FastAPI route'ları otomatik üretirim (`/trend?priority=**`) |
| 🧪 Test                    | Her modül için otomatik test iskeleti çıkarabilirim         |
| 🖥️ CLI                    | `python analyze.py --module /flow --priority=**` gibi       |
| 📊 UI menü                 | Streamlit/Dash için menüleri `priority` bazlı oluştururum   |
| 🧠 Sınıf Tabanlı Yorumlama | Her modüle özel analiz sınıfı oluşturma mantığını eklerim   |


"""