// A registration takes its date from the selected event, so the date is shown
// read-only and refreshed from the chosen option.
const eventSelect = document.getElementById("event_id");
const dateLabel = document.getElementById("date");

if (eventSelect && dateLabel) {
  const showSelectedDate = () => {
    const option = eventSelect.selectedOptions[0];
    const date = option ? option.dataset.date : "";
    dateLabel.textContent = date || dateLabel.dataset.empty;
  };
  eventSelect.addEventListener("change", showSelectedDate);
  showSelectedDate();
}
