import { defineRailway, github, preserve, project, service } from "railway/iac";

export default defineRailway((ctx) => {
  const expectedProject = process.env.FOODIEFY_RAILWAY_PROJECT_ID;
  const branch = process.env.FOODIEFY_STAGING_BRANCH;
  const region = process.env.FOODIEFY_STAGING_REGION;
  if (!ctx.projectName || !expectedProject || ctx.projectId !== expectedProject || ctx.environment !== "staging") {
    throw new Error("Select and verify the explicit Foodiefy staging project first.");
  }
  if (!branch || !region) throw new Error("Set reviewed staging branch and actual available region.");
  const shared = {
    APP_ENV: "staging", IMPORT_ENABLED: "false", IMPORT_ALLOW_PAID: "false",
    IMPORT_ALLOW_LOCAL_SOCIAL: "false", ENABLE_VISUAL_FALLBACK: "false",
    SUPABASE_URL: preserve(), IMPORT_DATABASE_URL: preserve(),
    STT_MODEL: "gpt-transcribe", RECIPE_EXTRACTOR_MODEL: "gpt-5-nano",
    VISUAL_MODEL: "gemini-2.5-flash", IMPORT_MAX_DURATION_SECONDS: "300",
    IMPORT_MAX_MEDIA_BYTES: "52428800", RAILWAY_DOCKERFILE_PATH: "Dockerfile",
  };
  const placement = { numReplicas: 1, region, sleepApplication: false,
    restartPolicyType: "ON_FAILURE" as const, restartPolicyMaxRetries: 5,
    preDeployCommand: [], limitOverride: { containers: { cpu: 1, memoryBytes: 1073741824, diskBytes: 1073741824 } } };
  const web = service("api", {
    source: github("PILTRAFILLA317/foodiefy_api", { branch }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    deploy: { ...placement, startCommand: "python -m scripts.web", healthcheckPath: "/health/ready", healthcheckTimeout: 90 },
    env: { ...shared, OPS_TOKEN: preserve() },
  });
  const worker = service("worker", {
    source: github("PILTRAFILLA317/foodiefy_api", { branch }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    deploy: { ...placement, startCommand: "python -m src.imports.worker", healthcheckPath: null },
    networking: { serviceDomains: {}, customDomains: {}, tcpProxies: {} },
    env: { ...shared, OPENAI_API_KEY: preserve(), GEMINI_API_KEY: preserve(),
      WORKER_POLL_SECONDS: "2", IMPORT_MIN_FREE_DISK_BYTES: "268435456", IMPORT_TEMP_TTL_SECONDS: "3600" },
  });
  return project(ctx.projectName, { resources: [web, worker] });
});
