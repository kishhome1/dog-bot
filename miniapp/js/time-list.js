// time-list.js — переиспользуемый редактор списка времён (HH:MM) с добавлением/
// удалением строк. Используется и онбордингом, и вкладкой «Настройки» → «Напоминания».

export function createTimeListEditor(listElementId, addButtonId, initialTimes) {
  let times = initialTimes.length ? [...initialTimes] : ["07:00"];

  function render() {
    const list = document.getElementById(listElementId);
    list.innerHTML = "";
    times.forEach((t, idx) => {
      const row = document.createElement("div");
      row.className = "time-row";
      row.innerHTML = `
        <input type="time" value="${t}" data-idx="${idx}" />
        <button class="remove-time" data-idx="${idx}" ${times.length <= 1 ? "disabled" : ""}>✕</button>
      `;
      list.appendChild(row);
    });

    list.querySelectorAll('input[type="time"]').forEach((input) => {
      input.addEventListener("change", (e) => {
        times[Number(e.target.dataset.idx)] = e.target.value;
      });
    });
    list.querySelectorAll(".remove-time").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        if (times.length <= 1) return;
        times.splice(Number(e.target.dataset.idx), 1);
        render();
      });
    });
  }

  document.getElementById(addButtonId).addEventListener("click", () => {
    times.push("12:00");
    render();
  });

  return {
    render,
    getTimes: () => times,
    setTimes(newTimes) {
      times = newTimes.length ? [...newTimes] : ["07:00"];
      render();
    },
  };
}
