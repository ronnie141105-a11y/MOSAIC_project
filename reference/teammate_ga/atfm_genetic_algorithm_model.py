"""
ATFM Genetic Algorithm Optimization Model for TMA TSN
Based on Section 2.4 and Chapter 3 specifications.
"""

import random
import numpy as np

# ==========================================
# 1. PROBLEM CONFIGURATION & PARAMETERS
# ==========================================
POPULATION_SIZE = 80       # Kích thước quần thể (50-150)
MAX_GENERATIONS = 150      # Số thế hệ tối đa (100-300)
CROSSOVER_RATE = 0.8       # Xác suất lai ghép (Pc)
MUTATION_RATE = 0.1        # Xác suất đột biến (Pm)
ELITISM_PERCENTAGE = 0.1   # Tỷ lệ bảo toàn cá thể tốt nhất (5-10%)

CAPACITY_LIMIT = 42        # Năng lực khả dụng (available capacity: 42 slot/giờ)
LAMBDA_PENALTY = 1000.0    # Trọng số phạt (lambda) khi vi phạm ràng buộc năng lực

# Định nghĩa các loại biện pháp (mi)
# 0: Không áp dụng
# 1: Ground Delay (GDP) - mức độ tính bằng phút
# 2: Speed Adjustment - mức độ tính bằng % giảm tốc độ
MEASURE_TYPES = [0, 1, 2]
GDP_LEVELS = [0, 5, 10, 15, 20]       # phút
SPEED_LEVELS = [0, 5, 10, 15]        # % giảm


# ==========================================
# 2. FLIGHT & COST DEFINITIONS
# ==========================================
class Flight:
    def __init__(self, flight_id, scheduled_time, sector_slot):
        self.flight_id = flight_id
        self.scheduled_time = scheduled_time  # Thời gian đến ban đầu (phút tính từ mốc)
        self.sector_slot = sector_slot        # Khung thời gian/slot mà chuyến bay đi qua TMA


def calculate_cost(measure_type, level):
    """
    Tính chi phí quy đổi của biện pháp c(m_i, l_i)
    Ví dụ đơn giản hóa dựa trên thời gian chậm trễ hoặc độ lệch tốc độ.
    """
    if measure_type == 0:
        return 0.0
    elif measure_type == 1:
        # Ground Delay: Chi phí tuyến tính theo số phút chậm trễ
        return float(level) * 1.5
    elif measure_type == 2:
        # Speed Adjustment: Chi phí quy đổi do điều chỉnh tốc độ
        return float(level) * 1.0
    return 0.0


# ==========================================
# 3. CHROMOSOME & EVALUATION (FITNESS)
# ==========================================
class Individual:
    def __init__(self, chromosome=None):
        # chromosome: danh sách các gene, mỗi gene là tuple (measure_type, level)
        self.chromosome = chromosome if chromosome else []
        self.fitness = 0.0
        self.total_cost = 0.0
        self.penalty = 0.0


def evaluate_individual(individual, flights):
    """
    Giải mã nhiễm sắc thể, tính thời gian sau điều tiết, kiểm tra ràng buộc năng lực,
    tính chi phí tổng cộng và hàm thích nghi (Fitness).
    """
    total_cost = 0.0
    slot_counts = {}

    for i, gene in enumerate(individual.chromosome):
        m_type, level = gene
        flight = flights[i]
        
        # 1. Tính chi phí biện pháp
        total_cost += calculate_cost(m_type, level)
        
        # 2. Tính thời điểm đến mới sau điều tiết
        new_time = flight.scheduled_time
        if m_type == 1:  # Ground Delay
            new_time += level
        elif m_type == 2:  # Speed Adjustment (giả định làm chậm thời gian bay nhẹ)
            new_time += int(level * 0.5)
            
        # Xác định lại slot thời gian (ví dụ quy về khung giờ/phút quy ước)
        slot_key = new_time // 60
        slot_counts[slot_key] = slot_counts.get(slot_key, 0) + 1

    # 3. Kiểm tra ràng buộc năng lực (capacity violation penalty)
    penalty = 0.0
    for slot, count in slot_counts.items():
        if count > CAPACITY_LIMIT:
            excess = count - CAPACITY_LIMIT
            penalty += excess * excess  # Phạt bình phương mức vượt theo lý thuyết

    # 4. Tính hàm mục tiêu f = tổng chi phí + lambda * P
    objective_value = total_cost + LAMBDA_PENALTY * penalty

    # 5. Hàm thích nghi Fitness = 1 / (1 + f)
    fitness = 1.0 / (1.0 + objective_value)

    individual.total_cost = total_cost
    individual.penalty = penalty
    individual.fitness = fitness
    return fitness


def create_random_individual(num_flights):
    """Khởi tạo ngẫu nhiên một cá thể."""
    chromosome = []
    for _ in range(num_flights):
        m_type = random.choice(MEASURE_TYPES)
        if m_type == 1:
            level = random.choice(GDP_LEVELS)
        elif m_type == 2:
            level = random.choice(SPEED_LEVELS)
        else:
            level = 0
        chromosome.append((m_type, level))
    return Individual(chromosome)


# ==========================================
# 4. GENETIC OPERATORS (GA OPERATORS)
# ==========================================
def tournament_selection(population, k=3):
    """Chọn lọc Tournament (k=3 hoặc 5)"""
    selected = random.sample(population, k)
    selected.sort(key=lambda ind: ind.fitness, reverse=True)
    return selected[0]


def crossover(parent1, parent2):
    """Lai ghép một điểm (One-point crossover)"""
    if random.random() > CROSSOVER_RATE:
        return Individual(list(parent1.chromosome)), Individual(list(parent2.chromosome))
    
    point = random.randint(1, len(parent1.chromosome) - 1)
    child1_chromo = parent1.chromosome[:point] + parent2.chromosome[point:]
    child2_chromo = parent2.chromosome[:point] + parent1.chromosome[point:]
    
    return Individual(child1_chromo), Individual(child2_chromo)


def mutate(individual):
    """Đột biến cá thể (Uniform/Gaussian mutation)"""
    new_chromo = []
    for gene in individual.chromosome:
        if random.random() < MUTATION_RATE:
            m_type = random.choice(MEASURE_TYPES)
            if m_type == 1:
                level = random.choice(GDP_LEVELS)
            elif m_type == 2:
                level = random.choice(SPEED_LEVELS)
            else:
                level = 0
            new_chromo.append((m_type, level))
        else:
            new_chromo.append(gene)
    return Individual(new_chromo)


# ==========================================
# 5. MAIN OPTIMIZATION LOOP
# ==========================================
def run_atfm_genetic_algorithm(flights):
    num_flights = len(flights)
    
    # Khởi tạo quần thể ban đầu
    population = [create_random_individual(num_flights) for _ in range(POPULATION_SIZE)]
    
    # Đánh giá ban đầu
    for ind in population:
        evaluate_individual(ind, flights)
        
    best_overall = max(population, key=lambda ind: ind.fitness)
    no_improvement_count = 0

    print(f"Bắt đầu chạy Thuật toán Di truyền (GA) cho {num_flights} chuyến bay...")
    print(f"Khởi tạo quần thể: {POPULATION_SIZE} cá thể, Số thế hệ tối đa: {MAX_GENERATIONS}\n")

    for generation in range(MAX_GENERATIONS):
        # Sắp xếp quần thể theo fitness giảm dần
        population.sort(key=lambda ind: ind.fitness, reverse=True)
        
        current_best = population[0]
        if current_best.fitness > best_overall.fitness:
            best_overall = Individual(list(current_best.chromosome))
            best_overall.fitness = current_best.fitness
            best_overall.total_cost = current_best.total_cost
            best_overall.penalty = current_best.penalty
            no_improvement_count = 0
        else:
            no_improvement_count += 1

        # Điều kiện dừng: Không cải thiện trong 30 thế hệ liên tiếp
        if no_improvement_count >= 30:
            print(f"Đạt điều kiện dừng tại thế hệ {generation}: Không cải thiện fitness trong 30 thế hệ liên tiếp.")
            break

        # Elitism: Bảo toàn cá thể tốt nhất (5-10%)
        elite_count = int(POPULATION_SIZE * ELITISM_PERCENTAGE)
        new_population = [Individual(list(ind.chromosome)) for ind in population[:elite_count]]

        # Tạo thế hệ mới qua chọn lọc, lai ghép, đột biến
        while len(new_population) < POPULATION_SIZE:
            parent1 = tournament_selection(population, k=3)
            parent2 = tournament_selection(population, k=3)
            
            child1, child2 = crossover(parent1, parent2)
            child1 = mutate(child1)
            child2 = mutate(child2)
            
            evaluate_individual(child1, flights)
            evaluate_individual(child2, flights)
            
            new_population.append(child1)
            if len(new_population) < POPULATION_SIZE:
                new_population.append(child2)

        population = new_population

        if generation % 10 == 0 or generation == MAX_GENERATIONS - 1:
            print(f"Thế hệ {generation:3d} | Best Fitness: {best_overall.fitness:.6f} | Cost: {best_overall.total_cost:.2f} | Penalty: {best_overall.penalty:.2f}")

    return best_overall


# ==========================================
# 6. EXECUTION SCRIPT
# ==========================================
if __name__ == "__main__":
    # Giả lập dữ liệu đầu vào cho một tập gồm 20 chuyến bay đến TMA TSN
    random.seed(42)
    sample_flights = [
        Flight(flight_id=f"VN{100+i}", scheduled_time=120 + i * 2, sector_slot=2)
        for i in range(20)
    ]

    # Chạy mô hình tối ưu GA
    best_solution = run_atfm_genetic_algorithm(sample_flights)

    print("\n==========================================")
    print(" KẾT QUẢ TỐI ƯU HÓA PHƯƠNG ÁN ATFM (GA)")
    print("==========================================")
    print(f"Tổng chi phí quy đổi: {best_solution.total_cost:.2f}")
    print(f"Mức vi phạm ràng buộc (Penalty): {best_solution.penalty:.2f}")
    print("\nChi tiết phân bổ biện pháp cho từng chuyến bay:")
    
    measure_names = {0: "Không áp dụng", 1: "Ground Delay (GDP)", 2: "Speed Adjustment"}
    for idx, (m_type, level) in enumerate(best_solution.chromosome):
        f = sample_flights[idx]
        if m_type == 1:
            detail = f"{level} phút"
        elif m_type == 2:
            detail = f"giảm {level}% tốc độ"
        else:
            detail = "N/A"
        print(f" - Chuyến {f.flight_id} (Giờ gốc: {f.scheduled_time}p): {measure_names[m_type]} -> {detail}")