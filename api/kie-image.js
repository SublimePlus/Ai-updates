// Vercel serverless proxy for Kie.ai "GPT Image 2.5 Flare" text-to-image.
// Keeps KIE_API_KEY on the server. If IMAGE_STUDIO_PASSCODE is set, callers
// must send it in the x-studio-passcode header so strangers can't spend credits.
//
//   POST /api/kie-image        {prompt, aspect_ratio?, resolution?, background?} -> {taskId}
//   GET  /api/kie-image?taskId -> {state, urls, failMsg, costTime}

const KIE_BASE = "https://api.kie.ai/api/v1/jobs";
const MODEL = "gpt-image-2-5-flare-text-to-image";

const ASPECTS = ["auto", "1:1", "3:2", "2:3", "16:9", "9:16", "4:3", "3:4", "21:9", "27:16", "16:27", "9:8", "8:9"];
const ONE_K_ONLY = ["27:16", "16:27", "9:8", "8:9"];
const RESOLUTIONS = ["1K", "2K", "4K"];
const BACKGROUNDS = ["auto", "opaque", "transparent"];

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

async function kie(path, init) {
  const resp = await fetch(`${KIE_BASE}/${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${process.env.KIE_API_KEY}`,
      "Content-Type": "application/json",
    },
  });
  const data = await resp.json().catch(() => ({}));
  // Kie returns errors both as HTTP status and as body.code
  const code = data.code ?? resp.status;
  if (!resp.ok || code !== 200) {
    const err = new Error(data.msg || `Kie.ai error ${code}`);
    err.status = code >= 400 && code < 600 ? code : 502;
    throw err;
  }
  return data.data;
}

async function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  if (typeof req.body === "string") return JSON.parse(req.body || "{}");
  let raw = "";
  for await (const chunk of req) raw += chunk;
  return JSON.parse(raw || "{}");
}

module.exports = async (req, res) => {
  if (!process.env.KIE_API_KEY) {
    return send(res, 500, { error: "KIE_API_KEY is not configured on the server" });
  }
  const passcode = process.env.IMAGE_STUDIO_PASSCODE;
  if (passcode && req.headers["x-studio-passcode"] !== passcode) {
    return send(res, 401, { error: "Wrong or missing studio passcode" });
  }

  try {
    if (req.method === "POST") {
      let body;
      try { body = await readBody(req); } catch { return send(res, 400, { error: "Invalid JSON body" }); }

      const prompt = String(body.prompt || "").trim();
      const aspect_ratio = body.aspect_ratio || "auto";
      const resolution = body.resolution || "1K";
      const background = body.background || "auto";

      if (!prompt) return send(res, 400, { error: "prompt is required" });
      if (prompt.length > 20000) return send(res, 400, { error: "prompt exceeds 20000 characters" });
      if (!ASPECTS.includes(aspect_ratio)) return send(res, 400, { error: "invalid aspect_ratio" });
      if (!RESOLUTIONS.includes(resolution)) return send(res, 400, { error: "invalid resolution" });
      if (!BACKGROUNDS.includes(background)) return send(res, 400, { error: "invalid background" });
      if (ONE_K_ONLY.includes(aspect_ratio) && resolution !== "1K") {
        return send(res, 400, { error: `${aspect_ratio} supports 1K only` });
      }

      const data = await kie("createTask", {
        method: "POST",
        body: JSON.stringify({ model: MODEL, input: { prompt, aspect_ratio, resolution, background } }),
      });
      return send(res, 200, { taskId: data.taskId });
    }

    if (req.method === "GET") {
      const taskId = new URL(req.url, "http://x").searchParams.get("taskId");
      if (!taskId) return send(res, 400, { error: "taskId is required" });
      const data = await kie(`recordInfo?taskId=${encodeURIComponent(taskId)}`, { method: "GET" });
      let urls = [];
      if (data.resultJson) {
        try { urls = JSON.parse(data.resultJson).resultUrls || []; } catch { /* leave empty */ }
      }
      return send(res, 200, {
        taskId: data.taskId,
        state: data.state,
        urls,
        failMsg: data.failMsg || null,
        costTime: data.costTime || null,
      });
    }

    res.setHeader("Allow", "GET, POST");
    return send(res, 405, { error: "Method not allowed" });
  } catch (err) {
    return send(res, err.status || 502, { error: err.message || "Upstream error" });
  }
};
