document.addEventListener("DOMContentLoaded", () => {
  const apiKeyInput = document.getElementById("apiKey");
  apiKeyInput.value = "s8u6HwiPRjZ0xIMHss--v0RGtgXwfg-Wkaal6ZnNpOU";
  const positivePromptInput = document.getElementById("positivePrompt");
  const negativePromptInput = document.getElementById("negativePrompt");
  const widthInput = document.getElementById("width");
  const heightInput = document.getElementById("height");
  const stepsInput = document.getElementById("steps");
  const scaleInput = document.getElementById("scale");
  const seedInput = document.getElementById("seed");
  const generateBtn = document.getElementById("generateBtn");
  const statusDiv = document.getElementById("status");
  const imageGallery = document.getElementById("image-gallery");

  const API_BASE_URL = "https://api.idlecloud.cc/api";

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const pollForResult = async (jobId, apiKey) => {
    const headers = {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    };

    while (true) {
      try {
        const resultRes = await fetch(`${API_BASE_URL}/get_result/${jobId}`, {
          headers,
        });
        const resultData = await resultRes.json();

        if (!resultRes.ok) {
          const errorDetails = resultData.error || JSON.stringify(resultData);
          throw new Error(`获取结果失败: ${errorDetails}`);
        }
        statusDiv.textContent = `当前任务状态: ${resultData.status || "查询中..."}`;

        if (resultData.status === "completed") {
          let imageFound = false;
          if (resultData.image_base64) {
            const img = document.createElement("img");
            img.src = `data:image/png;base64,${resultData.image_base64}`;
            imageGallery.prepend(img);
            imageFound = true;
          } else if (resultData.image_url) {
            const img = document.createElement("img");
            img.src = resultData.image_url;
            imageGallery.prepend(img);
            imageFound = true;
          }

          if (imageFound) {
            return "图片生成成功!";
          } else {
            throw new Error(
              "任务完成但未返回图片数据。响应: " + JSON.stringify(resultData)
            );
          }
        } else if (resultData.status === "failed") {
          throw new Error(`任务失败: ${resultData.error || "未知错误"}`);
        }

        await sleep(5000); // Wait 5 seconds before polling again
      } catch (error) {
        throw error;
      }
    }
  };

  const handleGenerateClick = async () => {
    const apiKey = apiKeyInput.value.trim();
    const positivePrompt = positivePromptInput.value.trim();

    if (!apiKey) {
      alert("请输入您的 API Key。");
      return;
    }
    if (!positivePrompt) {
      alert("请输入正向提示词。");
      return;
    }

    generateBtn.disabled = true;
    statusDiv.textContent = "正在提交任务...";
    imageGallery.innerHTML = ""; // Clear previous results

        const payload = {
            model: "nai-diffusion-4-5-full",
            positivePrompt: positivePrompt,
            negativePrompt: negativePromptInput.value.trim(),
            qualityToggle: false,
            scale: parseFloat(scaleInput.value),
            steps: parseInt(stepsInput.value),
            width: parseInt(widthInput.value),
            height: parseInt(heightInput.value),
            promptGuidanceRescale: 0,
            noise_schedule: "karras",
            sampler: "k_euler",
            sm: false,
            sm_dyn: false,
            decrisp: false,
            variety: false,
            n_samples: 1,
            prefer_brownian: true,
            deliberate_euler_ancestral_bug: false,
            legacy: false,
            legacy_uc: false,
            legacy_v3_extend: false,
            ucPreset: 1,
            autoSmea: false,
            use_coords: false,
            use_upscale_credits: false
        };

    if (seedInput.value) {
      payload.seed = parseInt(seedInput.value);
    }

    const headers = {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    };

    try {
      const submitRes = await fetch(`${API_BASE_URL}/generate_image`, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(payload),
      });

      const submitResponse = await submitRes.json();
      if (!submitRes.ok) {
        const errorDetails =
          submitResponse.error || JSON.stringify(submitResponse);
        throw new Error(`提交任务失败: ${errorDetails}`);
      }

      const { job_id } = submitResponse;
      if (!job_id) {
        throw new Error("提交成功，但未返回 Job ID。");
      }

      statusDiv.textContent = `任务已提交, Job ID: ${job_id}. 正在轮询结果...`;

      const finalMessage = await pollForResult(job_id, apiKey);
      statusDiv.textContent = finalMessage;
    } catch (error) {
      console.error("发生错误:", error);
      statusDiv.textContent = `错误: ${error.message}`;
    } finally {
      generateBtn.disabled = false;
    }
  };

  generateBtn.addEventListener("click", handleGenerateClick);
});
