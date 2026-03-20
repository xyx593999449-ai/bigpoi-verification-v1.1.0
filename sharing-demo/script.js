const body = document.body;
const speakerToggle = document.getElementById("speakerToggle");
const sectionLabel = document.getElementById("currentSectionLabel");
const progressBar = document.getElementById("progressBar");
const sections = Array.from(document.querySelectorAll("[data-section-title]"));
const railLinks = Array.from(document.querySelectorAll(".rail-link"));

const setActiveSection = (sectionId) => {
  const currentIndex = sections.findIndex((section) => section.id === sectionId);
  const safeIndex = currentIndex === -1 ? 0 : currentIndex;
  const activeSection = sections[safeIndex];

  sectionLabel.textContent = activeSection.dataset.sectionTitle;
  progressBar.style.width = `${((safeIndex + 1) / sections.length) * 100}%`;

  railLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.target === sectionId);
  });
};

speakerToggle.addEventListener("click", () => {
  body.classList.toggle("show-speaker");
  speakerToggle.textContent = body.classList.contains("show-speaker")
    ? "隐藏补充说明"
    : "显示补充说明";
});

const observer = new IntersectionObserver(
  (entries) => {
    const visibleEntries = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio);

    if (visibleEntries.length > 0) {
      setActiveSection(visibleEntries[0].target.id);
    }
  },
  {
    rootMargin: "-22% 0px -48% 0px",
    threshold: [0.25, 0.5, 0.75]
  }
);

sections.forEach((section) => observer.observe(section));
setActiveSection(sections[0].id);
