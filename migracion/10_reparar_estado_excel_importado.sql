-- Separa el ciclo de vida del período de la importación del Excel oficial.
-- "Excel Importado" dejó de ser un estado válido del período: la existencia y
-- validación del archivo se consulta en excel_importados.

BEGIN;

UPDATE inventario_periodos AS p
SET estado = CASE
    WHEN EXISTS (
        SELECT 1
        FROM auditoria_resultados AS ar
        WHERE ar.periodo_id = p.id
    ) THEN 'Auditado'
    WHEN EXISTS (
        SELECT 1
        FROM conteo_detalle AS cd
        WHERE cd.periodo_id = p.id
          AND cd.fue_cargado = TRUE
    ) THEN 'Cargado'
    ELSE 'Abierto'
END
WHERE p.estado = 'Excel Importado';

COMMIT;
