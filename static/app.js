(function () {
  "use strict";

  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.getAttribute("data-copy") || "";
      function done() {
        if (!btn.dataset.originalHtml) {
          btn.dataset.originalHtml = btn.innerHTML;
        }
        btn.textContent = "已复制";
        window.setTimeout(function () {
          btn.innerHTML = btn.dataset.originalHtml;
        }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(function () {
          fallbackCopy(text, done);
        });
      } else {
        fallbackCopy(text, done);
      }
    });
  });

  function fallbackCopy(text, done) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      done();
    } catch (err) {
      window.prompt("请手动复制回访码：", text);
    }
    document.body.removeChild(area);
  }

  document.querySelectorAll("textarea[data-counter]").forEach(function (field) {
    if (!field.id) return;
    var output = document.querySelector('[data-counter-for="' + field.id + '"]');
    if (!output) return;
    var update = function () {
      output.textContent = String(field.value.length);
    };
    field.addEventListener("input", update);
    update();
  });

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var message = form.getAttribute("data-confirm") || "确定执行这个操作吗？";
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });
})();
