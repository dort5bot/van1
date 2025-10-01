# analysis/health.py
class AnalysisHealthMonitor:
    async def check_module_health(self) -> Dict[str, bool]:
        """Tüm modüllerin sağlık durumunu kontrol et"""
        health_status = {}
        
        for module_name, module in self.modules.items():
            try:
                # Timeout ile health check
                await asyncio.wait_for(module.health_check(), timeout=5.0)
                health_status[module_name] = True
            except Exception as e:
                health_status[module_name] = False
                logger.error(f"Module {module_name} health check failed: {e}")
        
        return health_status