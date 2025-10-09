# utils/handler_loader.py
#v1008
import importlib
import pkgutil
import logging
import sys
from pathlib import Path
from aiogram import Dispatcher

logger = logging.getLogger(__name__)

async def load_handlers(dispatcher: Dispatcher) -> dict:
    """handlers klasöründeki tüm modülleri yükler ve router'a ekler"""
    results = {"loaded": 0, "failed": 0}

    handlers_dir = Path("handlers")
    
    if not handlers_dir.exists():
        logger.error(f"❌ Handlers directory not found: {handlers_dir}")
        return results
    
    # Tüm handler dosyalarını tara
    for file_path in handlers_dir.glob("*.py"):
        if file_path.name == "__init__.py":
            continue
            
        module_name = file_path.stem
        try:
            # Modülü import et
            spec = importlib.util.spec_from_file_location(f"handlers.{module_name}", file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, "router"):
                dispatcher.include_router(module.router)
                results["loaded"] += 1
                logger.info(f"✅ Handler yüklendi: {module_name}")
            else:
                results["failed"] += 1
                logger.warning(f"⚠️ Router bulunamadı: {module_name}")
                
        #except Exception as e:
            #results["failed"] += 1
            #logger.error(f"❌ Handler yüklenirken hata: {module_name} - {e}")
    
        except Exception as e:
            results["failed"] += 1
            logger.exception(f"❌ Handler yüklenirken hata: {module_name}")



    logger.info(f"📊 Handler yükleme sonucu: {results['loaded']} başarılı, {results['failed']} başarısız")
    return results


#clear_handler_cache fonksiyonu
async def clear_handler_cache():
    """Reload için cache temizleme"""
    modules_to_remove = []
    
    for key in list(sys.modules.keys()):
        if key.startswith("handlers."):
            modules_to_remove.append(key)
    
    for module_name in modules_to_remove:
        try:
            del sys.modules[module_name]
            logger.debug(f"🧹 Cache temizlendi: {module_name}")
        except Exception as e:
            logger.warning(f"⚠️ Cache temizlenemedi {module_name}: {e}")
