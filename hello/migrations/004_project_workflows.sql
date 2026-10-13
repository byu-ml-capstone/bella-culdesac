ALTER TABLE projects ADD COLUMN IF NOT EXISTS workflow_statuses JSONB;

UPDATE projects
SET workflow_statuses = workflow_templates.statuses
FROM workflow_templates
WHERE projects.workflow_statuses IS NULL
  AND projects.workflow_template_id = workflow_templates.id;
