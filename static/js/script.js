/**
 * MEDTRACK - MAIN SCRIPT FILE
 * Handles all interactive functionality
 */

document.addEventListener('DOMContentLoaded', () => {
  // ======================
  // 1. SIDEBAR TOGGLE
  // ======================
  const sidebar = document.getElementById('sidebar');
  const sidebarToggle = document.getElementById('sidebarToggle');
  const closeSidebar = document.getElementById('closeSidebar');

  if (sidebar && sidebarToggle) {
    // Mobile sidebar toggle
    sidebarToggle.addEventListener('click', () => {
      sidebar.classList.add('active');
      document.body.style.overflow = 'hidden'; // Prevent scrolling when sidebar is open
    });

    // Close sidebar button
    if (closeSidebar) {
      closeSidebar.addEventListener('click', () => {
        sidebar.classList.remove('active');
        document.body.style.overflow = '';
      });
    }

    // Close when clicking outside
    document.addEventListener('click', (e) => {
      const isClickInside = sidebar.contains(e.target) || e.target === sidebarToggle;
      if (!isClickInside) {
        sidebar.classList.remove('active');
        document.body.style.overflow = '';
      }
    });
  }

  // ======================
  // 2. ROLE TOGGLE (LOGIN/REGISTER)
  // ======================
  const roleButtons = document.querySelectorAll('.role-btn');
  const roleInput = document.getElementById('role-input');

  if (roleButtons.length && roleInput) {
    roleButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        // Update active state
        roleButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        // Update ARIA-pressed for accessibility
        roleButtons.forEach(b => b.setAttribute('aria-pressed', 'false'));
        btn.setAttribute('aria-pressed', 'true');
        
        // Update hidden input
        roleInput.value = btn.dataset.role;
      });
    });
  }

  // ======================
  // 3. PRESCRIPTION FORM (DOCTOR DASHBOARD)
  // ======================
  const prescribeButtons = document.querySelectorAll('.btn-prescribe');
  const prescriptionForm = document.getElementById('prescription-form');
  const cancelPrescriptionBtn = document.getElementById('cancel-prescription');

  if (prescribeButtons.length && prescriptionForm) {
    prescribeButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const patientId = btn.dataset.patientId;
        document.getElementById('patient-id').value = `#${patientId}`;
        
        // Show form
        prescriptionForm.hidden = false;
        
        // Smooth scroll to form
        prescriptionForm.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest'
        });
      });
    });

    // Cancel prescription button
    if (cancelPrescriptionBtn) {
      cancelPrescriptionBtn.addEventListener('click', () => {
        prescriptionForm.hidden = true;
      });
    }
  }

  // ======================
  // 4. DROPDOWN MENUS
  // ======================
  const dropdowns = document.querySelectorAll('.dropdown');

  if (dropdowns.length) {
    dropdowns.forEach(dropdown => {
      const btn = dropdown.querySelector('.dropdown-btn');
      const menu = dropdown.querySelector('.dropdown-menu');

      if (btn && menu) {
        // Toggle menu on button click
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const isOpen = menu.style.opacity === '1';
          
          // Close all other dropdowns first
          document.querySelectorAll('.dropdown-menu').forEach(m => {
            m.style.opacity = '0';
            m.style.visibility = 'hidden';
          });
          
          // Toggle current dropdown
          if (!isOpen) {
            menu.style.opacity = '1';
            menu.style.visibility = 'visible';
          }
        });
      }
    });

    // Close dropdowns when clicking elsewhere
    document.addEventListener('click', () => {
      document.querySelectorAll('.dropdown-menu').forEach(menu => {
        menu.style.opacity = '0';
        menu.style.visibility = 'hidden';
      });
    });
  }

  // ======================
  // 5. MEDICATION TRACKING (PATIENT DASHBOARD)
  // ======================
  const confirmButtons = document.querySelectorAll('.btn-confirm');

  if (confirmButtons.length) {
    confirmButtons.forEach(btn => {
      btn.addEventListener('click', async () => {
        const medId = btn.dataset.medicationId;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...';
        
        try {
          // Simulate API call
          await new Promise(resolve => setTimeout(resolve, 1000));
          btn.classList.remove('btn-confirm');
          btn.classList.add('btn-secondary');
          btn.innerHTML = '<i class="fas fa-check"></i> Taken';
        } catch (error) {
          console.error('Error:', error);
          btn.disabled = false;
          btn.innerHTML = '<i class="fas fa-times"></i> Failed';
        }
      });
    });
  }
});

// ======================
// HELPER FUNCTIONS
// ======================
function debounce(func, timeout = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => { func.apply(this, args); }, timeout);
  };
}