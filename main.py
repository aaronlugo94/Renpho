import os
import pytz
from datetime import datetime
import daily_renpho
import job_dieta

TZ = pytz.timezone(os.getenv("TZ", "America/Phoenix"))

def main():
    print(f"\n[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}] Iniciando Sistema de Control Autónomo...")
    
    print("--- FASE 1: Ingesta Biométrica Diaria ---")
    ingesta_exitosa = daily_renpho.ejecutar_diario()
    
    hoy = datetime.now(TZ)
    if hoy.weekday() == 6: # 6 = Domingo
        print("--- FASE 2: Domingo detectado. Evaluando Lazo Cerrado Metabólico ---")
        if ingesta_exitosa:
            job_dieta.ejecutar_job()
        else:
            print("⚠️ FASE 2 abortada: La ingesta diaria falló. Se protege el cálculo.")
    else:
        print("--- FASE 2: Omitida. El ajuste de dieta se ejecuta los domingos. ---")

if __name__ == "__main__":
    main()
